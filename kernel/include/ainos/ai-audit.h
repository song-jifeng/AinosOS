/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Audit Module - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI security audit and logging subsystem providing system call
 * auditing, file access monitoring, network auditing, AI anomaly
 * detection, and audit log rotation.
 */

#ifndef _AINOS_AI_AUDIT_H
#define _AINOS_AI_AUDIT_H

#include <linux/types.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/security.h>
#include <linux/lsm_hooks.h>
#include <linux/integrity.h>

/* Module identification */
#define AI_AUDIT_MODULE_NAME		"ai_audit"
#define AI_AUDIT_MODULE_VERSION		"1.0.0"
#define AI_AUDIT_MODULE_DESC		"Ainos AI Audit Module"
#define AI_AUDIT_MODULE_AUTHOR		"Ainos Kernel Team"

/* Device interface */
#define AI_AUDIT_DEVICE_NAME		"ai-audit"
#define AI_AUDIT_CLASS_NAME		"ai-audit"
#define AI_AUDIT_MAX_DEVICES		4

/* IOCTL commands */
#define AI_AUDIT_IOC_MAGIC		0xB3

#define AI_AUDIT_IOCTL_GET_INFO		_IOR(AI_AUDIT_IOC_MAGIC, 0x01, struct ai_audit_info)
#define AI_AUDIT_IOCTL_ENABLE		_IO(AI_AUDIT_IOC_MAGIC, 0x02)
#define AI_AUDIT_IOCTL_DISABLE		_IO(AI_AUDIT_IOC_MAGIC, 0x03)
#define AI_AUDIT_IOCTL_GET_STATUS	_IOR(AI_AUDIT_IOC_MAGIC, 0x04, struct ai_audit_status)
#define AI_AUDIT_IOCTL_GET_LOG		_IOR(AI_AUDIT_IOC_MAGIC, 0x05, struct ai_audit_log_entry)
#define AI_AUDIT_IOCTL_GET_LOGS		_IOWR(AI_AUDIT_IOC_MAGIC, 0x06, struct ai_audit_log_query)
#define AI_AUDIT_IOCTL_SET_FILTER	_IOW(AI_AUDIT_IOC_MAGIC, 0x07, struct ai_audit_filter)
#define AI_AUDIT_IOCTL_CLEAR_FILTERS	_IO(AI_AUDIT_IOC_MAGIC, 0x08)
#define AI_AUDIT_IOCTL_GET_STATS	_IOR(AI_AUDIT_IOC_MAGIC, 0x09, struct ai_audit_stats)
#define AI_AUDIT_IOCTL_ROTATE_LOG	_IO(AI_AUDIT_IOC_MAGIC, 0x0A)
#define AI_AUDIT_IOCTL_SET_RULES	_IOW(AI_AUDIT_IOC_MAGIC, 0x0B, struct ai_audit_rules)
#define AI_AUDIT_IOCTL_ADD_WATCH	_IOW(AI_AUDIT_IOC_MAGIC, 0x0C, struct ai_audit_watch)
#define AI_AUDIT_IOCTL_REMOVE_WATCH	_IOW(AI_AUDIT_IOC_MAGIC, 0x0D, struct ai_audit_watch)
#define AI_AUDIT_IOCTL_GET_ANOMALIES	_IOR(AI_AUDIT_IOC_MAGIC, 0x0E, struct ai_audit_anomaly_report)
#define AI_AUDIT_IOCTL_GET_SYSCALLS	_IOR(AI_AUDIT_IOC_MAGIC, 0x0F, struct ai_audit_syscall_stats)
#define AI_AUDIT_IOCTL_SET_BACKLOG	_IOW(AI_AUDIT_IOC_MAGIC, 0x10, __u32)
#define AI_AUDIT_IOCTL_FLUSH_LOGS	_IO(AI_AUDIT_IOC_MAGIC, 0x11)
#define AI_AUDIT_IOCTL_ENABLE_AI	_IO(AI_AUDIT_IOC_MAGIC, 0x12)
#define AI_AUDIT_IOCTL_DISABLE_AI	_IO(AI_AUDIT_IOC_MAGIC, 0x13)
#define AI_AUDIT_IOCTL_GET_AI_ANALYSIS	_IOR(AI_AUDIT_IOC_MAGIC, 0x14, struct ai_audit_ai_analysis)
#define AI_AUDIT_IOCTL_SET_ALERT	_IOW(AI_AUDIT_IOC_MAGIC, 0x15, struct ai_audit_alert_config)
#define AI_AUDIT_IOCTL_GET_ALERTS	_IOR(AI_AUDIT_IOC_MAGIC, 0x16, struct ai_audit_alert_list)
#define AI_AUDIT_IOCTL_ACK_ALERT	_IOW(AI_AUDIT_IOC_MAGIC, 0x17, __u32)
#define AI_AUDIT_IOCTL_GET_FILE_ACCESS	_IOWR(AI_AUDIT_IOC_MAGIC, 0x18, struct ai_audit_file_access_query)
#define AI_AUDIT_IOCTL_GET_NET_AUDIT	_IOWR(AI_AUDIT_IOC_MAGIC, 0x19, struct ai_audit_net_query)
#define AI_AUDIT_IOCTL_SET_LOG_PATH	_IOW(AI_AUDIT_IOC_MAGIC, 0x1A, struct ai_audit_log_path)
#define AI_AUDIT_IOCTL_GET_AI_THREATS	_IOR(AI_AUDIT_IOC_MAGIC, 0x1B, struct ai_audit_threat_report)

#define AI_AUDIT_IOC_MAXNR		27

/* Audit event types */
enum ai_audit_event_type {
	AI_AUDIT_EVENT_SYSCALL		= 0,	/* System call audit */
	AI_AUDIT_EVENT_FILE_ACCESS	= 1,	/* File access audit */
	AI_AUDIT_EVENT_NET_CONNECT	= 2,	/* Network connection */
	AI_AUDIT_EVENT_PROCESS_CREATE	= 3,	/* Process creation */
	AI_AUDIT_EVENT_PROCESS_EXIT	= 4,	/* Process exit */
	AI_AUDIT_EVENT_USER_LOGIN	= 5,	/* User login */
	AI_AUDIT_EVENT_USER_LOGOUT	= 6,	/* User logout */
	AI_AUDIT_EVENT_MODULE_LOAD	= 7,	/* Kernel module load */
	AI_AUDIT_EVENT_MODULE_UNLOAD	= 8,	/* Kernel module unload */
	AI_AUDIT_EVENT_SECURITY		= 9,	/* Security violation */
	AI_AUDIT_EVENT_ANOMALY		= 10,	/* AI-detected anomaly */
	AI_AUDIT_EVENT_CONFIG_CHANGE	= 11,	/* Configuration change */
	AI_AUDIT_EVENT_PRIVILEGE	= 12,	/* Privilege escalation */
	AI_AUDIT_EVENT_MAC_POLICY	= 13,	/* MAC policy enforcement */
	AI_AUDIT_EVENT_INTEGRITY	= 14,	/* Integrity check */
	AI_AUDIT_EVENT_CRYPTO		= 15,	/* Cryptographic operation */
	AI_AUDIT_EVENT_DEVICE		= 16,	/* Device access */
	AI_AUDIT_EVENT_IPC		= 17,	/* IPC operation */
	AI_AUDIT_EVENT_MEMORY_PROTECT	= 18,	/* Memory protection */
	AI_AUDIT_EVENT_AI_ACTION	= 19,	/* AI-driven action */
};

/* Audit severity levels */
enum ai_audit_severity {
	AI_AUDIT_SEV_DEBUG		= 0,	/* Debug information */
	AI_AUDIT_SEV_INFO		= 1,	/* Informational */
	AI_AUDIT_SEV_NOTICE		= 2,	/* Normal but significant */
	AI_AUDIT_SEV_WARNING		= 3,	/* Warning condition */
	AI_AUDIT_SEV_ERROR		= 4,	/* Error condition */
	AI_AUDIT_SEV_CRITICAL		= 5,	/* Critical condition */
	AI_AUDIT_SEV_ALERT		= 6,	/* Immediate action needed */
	AI_AUDIT_SEV_EMERGENCY		= 7,	/* System is unusable */
};

/* Audit filtering rules */
enum ai_audit_filter_rule {
	AI_AUDIT_FILTER_ALLOW		= 0,	/* Allow/record */
	AI_AUDIT_FILTER_DENY		= 1,	/* Deny/suppress */
	AI_AUDIT_FILTER_AUDIT		= 2,	/* Force audit */
	AI_AUDIT_FILTER_EXCLUDE		= 3,	/* Exclude from audit */
};

/* AI anomaly types */
enum ai_audit_anomaly_type {
	AI_AUDIT_ANOMALY_BEHAVIORAL	= 0,	/* Behavioral anomaly */
	AI_AUDIT_ANOMALY_SEQUENCE	= 1,	/* Sequence anomaly */
	AI_AUDIT_ANOMALY_FREQUENCY	= 2,	/* Frequency anomaly */
	AI_AUDIT_ANOMALY_PRIVILEGE	= 3,	/* Privilege anomaly */
	AI_AUDIT_ANOMALY_NETWORK	= 4,	/* Network anomaly */
	AI_AUDIT_ANOMALY_FILE		= 5,	/* File access anomaly */
	AI_AUDIT_ANOMALY_RESOURCE	= 6,	/* Resource usage anomaly */
	AI_AUDIT_ANOMALY_TIMING		= 7,	/* Timing anomaly */
};

/* Audit status */
struct ai_audit_status {
	__u32			enabled;
	__u32			ai_enabled;
	__u32			log_count;
	__u32			log_capacity;
	__u32			filter_count;
	__u32			watch_count;
	__u32			backlog_limit;
	__u32			backlog_current;
	__u32			overflow_count;
	__u32			error_count;
	__u32			anomaly_count;
	__u32			alert_count;
	__u32			padding[4];
};

/* Audit log entry */
struct ai_audit_log_entry {
	__u64			event_id;
	__u64			timestamp;
	__u32			event_type;
	__u32			severity;
	__u32			pid;
	__u32			uid;
	__u32			gid;
	__u32			session_id;
	__u32			auid;
	__u32			success;
	__u64			syscall;
	__s64			exit_code;
	__u64			key;
	__u64			process_start_time;
	char			comm[16];
	char			exe_path[256];
	char			message[512];
	__u32			message_len;
	__u32			data_len;
	__u8			data[256];
	__u32			padding[4];
};

/* Log query */
struct ai_audit_log_query {
	__u64			start_time;
	__u64			end_time;
	__u32			event_type;
	__u32			severity_min;
	__u32			severity_max;
	__u32			pid;
	__u32			uid;
	__u32			max_entries;
	__u32			actual_entries;
	__u64			entries;
	__u32			total_available;
	__u32			padding[6];
};

/* Audit filter */
struct ai_audit_filter {
	__u32			filter_id;
	__u32			event_type;
	__u32			rule;
	__u32			field;
	__u64			value_mask;
	__u64			value_match;
	char			value_string[128];
	__u32			priority;
	__u32			flags;
	__u32			padding[4];
};

/* Audit rules */
struct ai_audit_rules {
	__u32			rule_count;
	__u32			flags;
	struct ai_audit_filter	filters[16];
	__u32			padding[8];
};

/* File watch */
struct ai_audit_watch {
	__u32			watch_id;
	char			path[256];
	__u32			watch_type;
	__u32			flags;
	__u32			mask;
	__u32			permissions;
	__u32			padding[8];
};

/* Stats */
struct ai_audit_stats {
	__u64			total_events;
	__u64			total_syscalls;
	__u64			total_file_access;
	__u64			total_net_events;
	__u64			total_process_events;
	__u64			total_user_events;
	__u64			total_security_events;
	__u64			total_anomalies;
	__u64			total_alerts;
	__u64			total_rotations;
	__u64			events_per_sec;
	__u64			bytes_written;
	__u64			bytes_read;
	__u64			overflow_dropped;
	__u64			errors;
	__u64			uptime_seconds;
	__u32			active_watches;
	__u32			active_filters;
	__u32			backlog_usage;
	__u32			padding[5];
};

/* System call statistics */
struct ai_audit_syscall_stats {
	__u64			total_syscalls;
	__u64			monitored_syscalls;
	__u64			blocked_syscalls;
	__u64			suspicious_syscalls;
	__u64			syscall_counts[512];
	__u32			padding[8];
};

/* Anomaly report */
struct ai_audit_anomaly_report {
	__u32			anomaly_id;
	__u64			timestamp;
	__u32			anomaly_type;
	__u32			severity;
	__u32			confidence;
	__u32			pid;
	__u32			uid;
	char			comm[16];
	char			description[256];
	__u64			related_event_id;
	__u32			action_taken;
	__u32			acked;
	__u32			padding[8];
};

/* AI analysis */
struct ai_audit_ai_analysis {
	__u64			analysis_time;
	__u32			events_analyzed;
	__u32			anomalies_found;
	__u32			threats_detected;
	__u32			false_positives;
	__u32			model_version;
	__u32			detection_rate;
	__u32			baseline_period_sec;
	__u32			learning_active;
	__u32			patterns_identified;
	__u32			padding[8];
};

/* Alert configuration */
struct ai_audit_alert_config {
	__u32			alert_id;
	__u32			event_type;
	__u32			severity_threshold;
	__u32			rate_threshold;
	__u32			time_window_sec;
	__u32			action;
	__u32			enabled;
	char			description[128];
	__u32			padding[4];
};

/* Alert list */
struct ai_audit_alert_list {
	__u32			max_alerts;
	__u32			actual_alerts;
	__u32			alert_ids[64];
	__u32			padding[8];
};

/* File access query */
struct ai_audit_file_access_query {
	__u64			start_time;
	__u64			end_time;
	char			path[256];
	__u32			pid;
	__u32			max_entries;
	__u32			actual_entries;
	__u64			entries;
	__u32			padding[8];
};

/* Network audit query */
struct ai_audit_net_query {
	__u64			start_time;
	__u64			end_time;
	__u32			src_port;
	__u32			dst_port;
	__u32			protocol;
	__u32			family;
	__u32			pid;
	__u32			max_entries;
	__u32			actual_entries;
	__u64			entries;
	__u32			padding[6];
};

/* Log path configuration */
struct ai_audit_log_path {
	char			path[256];
	__u32			max_size_mb;
	__u32			max_files;
	__u32			compression;
	__u32			padding[4];
};

/* Threat report */
struct ai_audit_threat_report {
	__u32			threat_count;
	__u32			high_priority;
	__u32			medium_priority;
	__u32			low_priority;
	__u32			threat_types[8];
	__u32			threat_counts[8];
	__u32			top_threats[16];
	__u32			padding[8];
};

/* Module info */
struct ai_audit_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			enabled;
	__u32			ai_enabled;
	__u32			log_entries;
	__u32			log_capacity;
	__u32			features;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_AUDIT_SYSFS_ENABLED		"enabled"
#define AI_AUDIT_SYSFS_AI_ENABLED	"ai_enabled"
#define AI_AUDIT_SYSFS_STATUS		"status"
#define AI_AUDIT_SYSFS_STATS		"stats"
#define AI_AUDIT_SYSFS_LOG_COUNT	"log_count"
#define AI_AUDIT_SYSFS_FILTERS		"filters"
#define AI_AUDIT_SYSFS_WATCHES		"watches"
#define AI_AUDIT_SYSFS_ANOMALIES	"anomalies"
#define AI_AUDIT_SYSFS_ALERTS		"alerts"
#define AI_AUDIT_SYSFS_BACKLOG		"backlog"
#define AI_AUDIT_SYSFS_FLUSH		"flush"
#define AI_AUDIT_SYSFS_ROTATE		"rotate"
#define AI_AUDIT_SYSFS_ANALYSIS		"analysis"

/* Internal kernel API */
struct ai_audit_context;

#ifdef CONFIG_AINOS_AI_AUDIT

/* Core audit operations */
int ai_audit_enable(void);
int ai_audit_disable(void);
int ai_audit_is_enabled(bool *enabled);
int ai_audit_get_status(struct ai_audit_status *status);
int ai_audit_get_info(struct ai_audit_info *info);

/* Event logging */
int ai_audit_log_event(struct ai_audit_log_entry *entry);
int ai_audit_log_syscall(int nr, pid_t pid, uid_t uid, int success,
			 long exit_code);
int ai_audit_log_file_access(const char *path, int mask, pid_t pid,
			     uid_t uid, int success);
int ai_audit_log_net_connect(__u32 src_ip, __u32 dst_ip, __u16 src_port,
			     __u16 dst_port, __u8 protocol, pid_t pid,
			     int success);
int ai_audit_log_process(pid_t pid, pid_t ppid, uid_t uid,
			 const char *comm, const char *filename,
			 int event_type);
int ai_audit_log_security(const char *msg, int severity, pid_t pid, uid_t uid);

/* Log management */
int ai_audit_get_logs(struct ai_audit_log_query *query);
int ai_audit_flush_logs(void);
int ai_audit_rotate_logs(void);
int ai_audit_set_log_path(const char *path, unsigned int max_size_mb,
			  unsigned int max_files);

/* Filtering */
int ai_audit_add_filter(struct ai_audit_filter *filter);
int ai_audit_remove_filter(unsigned int filter_id);
int ai_audit_clear_filters(void);

/* File watching */
int ai_audit_add_watch(struct ai_audit_watch *watch);
int ai_audit_remove_watch(unsigned int watch_id);

/* AI anomaly detection */
int ai_audit_ai_enable(void);
int ai_audit_ai_disable(void);
int ai_audit_ai_analyze(void);
int ai_audit_ai_get_analysis(struct ai_audit_ai_analysis *analysis);
int ai_audit_ai_get_anomalies(struct ai_audit_anomaly_report *reports,
			      int max_count, int *actual_count);
int ai_audit_ai_get_threats(struct ai_audit_threat_report *report);
int ai_audit_ai_detect_anomaly(struct ai_audit_log_entry *entry,
			       bool *is_anomaly, float *confidence);

/* Alerting */
int ai_audit_configure_alert(struct ai_audit_alert_config *config);
int ai_audit_get_alerts(struct ai_audit_alert_list *list);
int ai_audit_ack_alert(unsigned int alert_id);

/* Stats */
int ai_audit_get_stats(struct ai_audit_stats *stats);
int ai_audit_get_syscall_stats(struct ai_audit_syscall_stats *stats);
int ai_audit_reset_stats(void);

/* Backlog */
int ai_audit_set_backlog_limit(unsigned int limit);
int ai_audit_get_backlog_limit(unsigned int *limit);

/* System call interposition (for LSM integration) */
int ai_audit_syscall_entry(int nr, pid_t pid, uid_t uid);
int ai_audit_syscall_exit(int nr, long result);
int ai_audit_file_permission(const char *path, int mask);
int ai_audit_socket_connect(struct sock *sk, int family, int type,
			    int protocol);

#else /* !CONFIG_AINOS_AI_AUDIT */

static inline int ai_audit_enable(void)
{ return -ENODEV; }

static inline int ai_audit_disable(void)
{ return -ENODEV; }

static inline int ai_audit_is_enabled(bool *enabled)
{ *enabled = false; return 0; }

static inline int ai_audit_get_status(struct ai_audit_status *status)
{ return -ENODEV; }

static inline int ai_audit_get_info(struct ai_audit_info *info)
{ return -ENODEV; }

static inline int ai_audit_log_event(struct ai_audit_log_entry *entry)
{ return -ENODEV; }

static inline int ai_audit_log_syscall(int nr, pid_t pid, uid_t uid,
				       int success, long exit_code)
{ return -ENODEV; }

static inline int ai_audit_log_file_access(const char *path, int mask,
					   pid_t pid, uid_t uid, int success)
{ return -ENODEV; }

static inline int ai_audit_log_net_connect(__u32 src_ip, __u32 dst_ip,
					   __u16 src_port, __u16 dst_port,
					   __u8 protocol, pid_t pid,
					   int success)
{ return -ENODEV; }

static inline int ai_audit_log_process(pid_t pid, pid_t ppid, uid_t uid,
				       const char *comm, const char *filename,
				       int event_type)
{ return -ENODEV; }

static inline int ai_audit_log_security(const char *msg, int severity,
					pid_t pid, uid_t uid)
{ return -ENODEV; }

static inline int ai_audit_get_logs(struct ai_audit_log_query *query)
{ return -ENODEV; }

static inline int ai_audit_flush_logs(void)
{ return -ENODEV; }

static inline int ai_audit_rotate_logs(void)
{ return -ENODEV; }

static inline int ai_audit_set_log_path(const char *path,
					unsigned int max_size_mb,
					unsigned int max_files)
{ return -ENODEV; }

static inline int ai_audit_add_filter(struct ai_audit_filter *filter)
{ return -ENODEV; }

static inline int ai_audit_remove_filter(unsigned int filter_id)
{ return -ENODEV; }

static inline int ai_audit_clear_filters(void)
{ return -ENODEV; }

static inline int ai_audit_add_watch(struct ai_audit_watch *watch)
{ return -ENODEV; }

static inline int ai_audit_remove_watch(unsigned int watch_id)
{ return -ENODEV; }

static inline int ai_audit_ai_enable(void)
{ return -ENODEV; }

static inline int ai_audit_ai_disable(void)
{ return -ENODEV; }

static inline int ai_audit_ai_analyze(void)
{ return -ENODEV; }

static inline int ai_audit_ai_get_analysis(struct ai_audit_ai_analysis *a)
{ return -ENODEV; }

static inline int ai_audit_ai_get_anomalies(struct ai_audit_anomaly_report *r,
					    int max, int *actual)
{ return -ENODEV; }

static inline int ai_audit_ai_get_threats(struct ai_audit_threat_report *r)
{ return -ENODEV; }

static inline int ai_audit_ai_detect_anomaly(struct ai_audit_log_entry *e,
					     bool *is_anomaly, float *conf)
{ return -ENODEV; }

static inline int ai_audit_configure_alert(struct ai_audit_alert_config *c)
{ return -ENODEV; }

static inline int ai_audit_get_alerts(struct ai_audit_alert_list *list)
{ return -ENODEV; }

static inline int ai_audit_ack_alert(unsigned int alert_id)
{ return -ENODEV; }

static inline int ai_audit_get_stats(struct ai_audit_stats *stats)
{ return -ENODEV; }

static inline int ai_audit_get_syscall_stats(struct ai_audit_syscall_stats *s)
{ return -ENODEV; }

static inline int ai_audit_reset_stats(void)
{ return -ENODEV; }

static inline int ai_audit_set_backlog_limit(unsigned int limit)
{ return -ENODEV; }

static inline int ai_audit_get_backlog_limit(unsigned int *limit)
{ return -ENODEV; }

static inline int ai_audit_syscall_entry(int nr, pid_t pid, uid_t uid)
{ return 0; }

static inline int ai_audit_syscall_exit(int nr, long result)
{ return 0; }

static inline int ai_audit_file_permission(const char *path, int mask)
{ return 0; }

static inline int ai_audit_socket_connect(struct sock *sk, int family,
					  int type, int protocol)
{ return 0; }

#endif /* CONFIG_AINOS_AI_AUDIT */

#endif /* _AINOS_AI_AUDIT_H */