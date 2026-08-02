// SPDX-License-Identifier: GPL-2.0
// ================================================================
// Ainos OS - AI readahead 智能预读 (深度实现 v2.0.0)
// ================================================================
//
// 基于访问模式分析的智能预读预测引擎。
// 支持多种预测模型: 顺序访问、固定步长、随机访问检测。
// 提供 /proc/ai-readahead 接口用于监控和控制。
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │              AI readahead 预测引擎                        │
//   ├─────────────────────────────────────────────────────────┤
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  访问记录器                                      │   │
//   │  │  record() / record_batch() / confirm()          │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  模式分析器                                      │   │
//   │  │  Sequential: 连续页检测                         │   │
//   │  │  Strided: 固定步长检测                          │   │
//   │  │  Random: 分散访问检测                           │   │
//   │  │  Subpage: 同一页内访问                          │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  预测器                                         │   │
//   │  │  • 选择最佳模型                                 │   │
//   │  │  • 计算置信度                                   │   │
//   │  │  • 建议预读窗口大小                             │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  文件跟踪表 (hash + LRU)                        │   │
//   │  │  512 条, 链式 hash, LRU 淘汰                    │   │
//   │  └─────────────────────────────────────────────────┘   │
//   │                                                         │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  /proc/ai-readahead 接口                        │   │
//   │  │  status | files | config                        │   │
//   │  └─────────────────────────────────────────────────┘   │
//   └─────────────────────────────────────────────────────────┘
//
// 预测模型:
//   Sequential: offset[n] == offset[n-1] + 1 → 预测 offset+1
//   Strided: offset[n] - offset[n-1] == const → 预测 offset+stride
//   Random: 无规律 → 不预测 (建议小窗口)
// ================================================================

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/string.h>
#include <linux/list.h>
#include <linux/hash.h>
#include <linux/jhash.h>
#include <linux/atomic.h>
#include <linux/timekeeping.h>
#include <linux/version.h>

#include "ai_readahead.h"

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI readahead - intelligent pre-read predictor (deep implementation)");
MODULE_VERSION(AI_READAHEAD_VERSION);

/* ================================================================
 * 参数
 * ================================================================ */

static unsigned int hash_size = 512;
module_param(hash_size, uint, 0644);
MODULE_PARM_DESC(hash_size, "跟踪表 hash 大小");

static unsigned int max_confidence = 95;
module_param(max_confidence, uint, 0644);
MODULE_PARM_DESC(max_confidence, "最大置信度");

static unsigned int seq_window = 32;
module_param(seq_window, uint, 0644);
MODULE_PARM_DESC(seq_window, "顺序访问建议预读窗口 (页)");

static unsigned int stride_window = 16;
module_param(stride_window, uint, 0644);
MODULE_PARM_DESC(stride_window, "步长访问建议预读窗口 (页)");

static unsigned int random_window = 4;
module_param(random_window, uint, 0644);
MODULE_PARM_DESC(random_window, "随机访问建议预读窗口 (页)");

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 文件跟踪条目 */
struct ra_entry {
    char                   name[64];          /* 文件名 */
    struct ai_ra_pattern   pattern;           /* 访问模式 */
    u64                    total_accesses;
    u64                    sequential_accesses;
    u64                    random_accesses;
    u64                    correct_predictions;
    u64                    total_predictions;
    u64                    last_access_ns;
    struct list_head       lru_node;          /* LRU 链表 */
    struct hlist_node      hash_node;         /* Hash 链表 */
    spinlock_t             lock;
    bool                   valid;
};

/* 全局状态 */
static struct {
    /* Hash 表 */
    struct hlist_head  *hash_table;
    unsigned int        hash_size;

    /* LRU 列表 */
    struct list_head    lru_list;
    unsigned int        entry_count;
    unsigned int        entry_max;
    spinlock_t          lru_lock;

    /* 全局统计 */
    struct ai_ra_global_stats stats;
    spinlock_t          stats_lock;

    /* 模块启动时间 */
    unsigned long       start_jiffies;

    /* /proc 条目 */
    struct proc_dir_entry *proc_dir;
    struct proc_dir_entry *proc_status;
    struct proc_dir_entry *proc_files;
    struct proc_dir_entry *proc_config;

    bool initialized;
} g_ra;

/* ================================================================
 * Hash 和 LRU 操作
 * ================================================================ */

static unsigned int ra_hash(const char *name)
{
    return jhash(name, strnlen(name, 64), 0) % g_ra.hash_size;
}

static struct ra_entry *ra_lookup(const char *name)
{
    struct ra_entry *entry;
    unsigned int hash = ra_hash(name);

    hlist_for_each_entry(entry, &g_ra.hash_table[hash], hash_node) {
        if (entry->valid && strncmp(entry->name, name, 64) == 0)
            return entry;
    }
    return NULL;
}

/* 创建新条目 */
static struct ra_entry *ra_create(const char *name)
{
    struct ra_entry *entry;
    unsigned int hash = ra_hash(name);
    unsigned long flags;

    /* 检查是否已满，需要淘汰 */
    spin_lock_irqsave(&g_ra.lru_lock, flags);
    if (g_ra.entry_count >= g_ra.entry_max) {
        /* LRU 淘汰: 从链表头移除最久未使用的 */
        struct ra_entry *victim;
        list_for_each_entry(victim, &g_ra.lru_list, lru_node) {
            if (victim->valid) {
                hlist_del(&victim->hash_node);
                list_del(&victim->lru_node);
                victim->valid = false;
                g_ra.entry_count--;
                kfree(victim);
                break;
            }
        }
    }
    spin_unlock_irqrestore(&g_ra.lru_lock, flags);

    /* 分配新条目 */
    entry = kzalloc(sizeof(*entry), GFP_KERNEL);
    if (!entry)
        return NULL;

    /* 检查 hash 链长度: 如果链过长，先淘汰一个旧条目 */
    {
        struct ra_entry *chain_entry;
        int chain_len = 0;
        unsigned long __flags;
        spin_lock_irqsave(&g_ra.lru_lock, __flags);
        hlist_for_each_entry(chain_entry, &g_ra.hash_table[hash], hash_node) {
            if (chain_entry->valid) chain_len++;
        }
        /* 最大链长: 8，超过则淘汰同桶中最旧的 */
        if (chain_len >= 8) {
            struct ra_entry *victim = NULL;
            list_for_each_entry_reverse(chain_entry, &g_ra.lru_list, lru_node) {
                if (chain_entry->valid &&
                    ra_hash(chain_entry->name) == hash) {
                    victim = chain_entry;
                    break;
                }
            }
            if (victim) {
                hlist_del(&victim->hash_node);
                list_del(&victim->lru_node);
                victim->valid = false;
                g_ra.entry_count--;
                kfree(victim);
            }
        }
        spin_unlock_irqrestore(&g_ra.lru_lock, __flags);
    }

    strscpy(entry->name, name, sizeof(entry->name));
    entry->pattern.count = 0;
    entry->pattern.model = AI_RA_MODEL_UNKNOWN;
    entry->pattern.stride = 0;
    entry->pattern.stride_confidence = 0;
    entry->pattern.sequential_count = 0;
    entry->pattern.random_count = 0;
    entry->total_accesses = 0;
    entry->sequential_accesses = 0;
    entry->random_accesses = 0;
    entry->correct_predictions = 0;
    entry->total_predictions = 0;
    entry->last_access_ns = ktime_get_real_ns();
    spin_lock_init(&entry->lock);
    entry->valid = true;

    /* 加入 hash 表和 LRU */
    spin_lock_irqsave(&g_ra.lru_lock, flags);
    hlist_add_head(&entry->hash_node, &g_ra.hash_table[hash]);
    list_add_tail(&entry->lru_node, &g_ra.lru_list);
    g_ra.entry_count++;
    spin_unlock_irqrestore(&g_ra.lru_lock, flags);

    return entry;
}

/* 获取或创建条目 */
static struct ra_entry *ra_get_or_create(const char *name)
{
    struct ra_entry *entry;
    unsigned long flags;

    entry = ra_lookup(name);
    if (entry)
        return entry;

    entry = ra_create(name);
    return entry;
}

/* 更新 LRU (移动到尾部 = 最近使用) */
static void ra_update_lru(struct ra_entry *entry)
{
    unsigned long flags;

    spin_lock_irqsave(&g_ra.lru_lock, flags);
    list_move_tail(&entry->lru_node, &g_ra.lru_list);
    spin_unlock_irqrestore(&g_ra.lru_lock, flags);
}

/* ================================================================
 * 模式分析引擎
 * ================================================================ */

/* 分析访问模式并更新模式状态 */
static void analyze_pattern(struct ai_ra_pattern *pat, unsigned long offset)
{
    int i;

    if (pat->count == 0) {
        pat->offsets[0] = offset;
        pat->count = 1;
        pat->model = AI_RA_MODEL_UNKNOWN;
        return;
    }

    unsigned long last = pat->offsets[pat->count - 1];

    /* 1. 检查是否是同一页 */
    if (offset == last) {
        pat->model = AI_RA_MODEL_SUBPAGE;
        return;
    }

    /* 2. 检查顺序访问 */
    if (offset == last + 1) {
        pat->sequential_count++;
        pat->random_count = 0;

        if (pat->sequential_count >= 2) {
            pat->model = AI_RA_MODEL_SEQUENTIAL;
            pat->stride = 1;
            pat->stride_confidence = min(pat->stride_confidence + 15, 100u);
        }
    }
    /// 在 analyze_pattern() 中，检查步长一致性时增加最少样本数要求
    /* 3. 检查固定步长 — 需要至少 3 个点才能确认步长模式 */
    else if (pat->count >= 3) {
        unsigned long prev = pat->offsets[pat->count - 2];
        unsigned long s1 = last - prev;
        unsigned long s2 = offset - last;

        if (s1 == s2 && s1 > 0) {
            pat->stride = s1;
            pat->stride_confidence = min(pat->stride_confidence + 20, 100u);
            pat->model = AI_RA_MODEL_STRIDED;
            pat->sequential_count = 0;
            pat->random_count = 0;
        } else {
            /* 不是顺序也不是步长 */
            pat->random_count++;
            pat->sequential_count = 0;
            pat->stride_confidence = max(pat->stride_confidence - 5, 0);

            if (pat->random_count >= 3) {
                pat->model = AI_RA_MODEL_RANDOM;
            } else {
                pat->model = AI_RA_MODEL_UNKNOWN;
            }
        }
    }
    /* 4. 只有两个点，还不能确定模式 */
    else {
        unsigned long diff = offset - last;
        if (diff == 1) {
            pat->sequential_count++;
            pat->model = AI_RA_MODEL_SEQUENTIAL;
            pat->stride = 1;
            pat->stride_confidence = 30;
        } else {
            pat->stride = diff;
            pat->stride_confidence = 20;
            pat->model = AI_RA_MODEL_STRIDED;
        }
        pat->random_count = 0;
    }

    /* 记录偏移 (环形缓冲区) */
    if (pat->count < 8) {
        pat->offsets[pat->count++] = offset;
    } else {
        for (i = 1; i < 8; i++)
            pat->offsets[i - 1] = pat->offsets[i];
        pat->offsets[7] = offset;
    }
}

/* 根据模式生成预测 */
static struct ai_ra_prediction make_prediction(const struct ai_ra_pattern *pat)
{
    struct ai_ra_prediction pred = {0, 0, AI_RA_MODEL_UNKNOWN, 0};
    int last_idx;

    if (pat->count == 0)
        return pred;

    last_idx = pat->count - 1;
    pred.model = pat->model;

    switch (pat->model) {
    case AI_RA_MODEL_SEQUENTIAL:
        pred.predicted_offset = pat->offsets[last_idx] + 1;
        pred.confidence = min(pat->stride_confidence, max_confidence);
        pred.suggested_window = seq_window;
        break;

    case AI_RA_MODEL_STRIDED:
        pred.predicted_offset = pat->offsets[last_idx] + pat->stride;
        pred.confidence = min(pat->stride_confidence, max_confidence);
        pred.suggested_window = stride_window;
        break;

    case AI_RA_MODEL_RANDOM:
        /* 随机访问不预测，建议小窗口 */
        pred.confidence = 10;
        pred.suggested_window = random_window;
        break;

    case AI_RA_MODEL_SUBPAGE:
        /* 子页面访问，建议小窗口 */
        pred.predicted_offset = pat->offsets[last_idx];
        pred.confidence = 50;
        pred.suggested_window = 1;
        break;

    default:
        /* 未知模式，保守预测 */
        if (pat->count > 0) {
            pred.predicted_offset = pat->offsets[last_idx] + 1;
            pred.confidence = 20;
            pred.suggested_window = 8;
        }
        break;
    }

    return pred;
}

/* ================================================================
 * 核心 API
 * ================================================================ */

struct ai_ra_prediction ai_readahead_record(const char *filename,
                                             unsigned long offset)
{
    struct ra_entry *entry;
    struct ai_ra_prediction pred = {0, 0, AI_RA_MODEL_UNKNOWN, 8};
    unsigned long flags;

    if (!filename || !g_ra.initialized)
        return pred;

    entry = ra_get_or_create(filename);
    if (!entry)
        return pred;

    spin_lock_irqsave(&entry->lock, flags);

    entry->total_accesses++;
    entry->last_access_ns = ktime_get_real_ns();

    /* 分析模式 */
    analyze_pattern(&entry->pattern, offset);

    /* 更新统计 */
    switch (entry->pattern.model) {
    case AI_RA_MODEL_SEQUENTIAL:
        entry->sequential_accesses++;
        break;
    case AI_RA_MODEL_RANDOM:
        entry->random_accesses++;
        break;
    default:
        break;
    }

    /* 生成预测 */
    pred = make_prediction(&entry->pattern);
    entry->total_predictions++;

    /* 更新全局统计 */
    spin_lock(&g_ra.stats_lock);
    g_ra.stats.total_predictions++;
    switch (entry->pattern.model) {
    case AI_RA_MODEL_SEQUENTIAL: g_ra.stats.sequential_detected++; break;
    case AI_RA_MODEL_STRIDED:    g_ra.stats.strided_detected++; break;
    case AI_RA_MODEL_RANDOM:     g_ra.stats.random_detected++; break;
    default: break;
    }
    spin_unlock(&g_ra.stats_lock);

    spin_unlock_irqrestore(&entry->lock, flags);

    /* 更新 LRU */
    ra_update_lru(entry);

    return pred;
}
EXPORT_SYMBOL_GPL(ai_readahead_record);

void ai_readahead_confirm(const char *filename, unsigned long offset)
{
    struct ra_entry *entry;
    unsigned long flags;

    if (!filename || !g_ra.initialized)
        return;

    entry = ra_lookup(filename);
    if (!entry)
        return;

    spin_lock_irqsave(&entry->lock, flags);
    entry->correct_predictions++;

    /* 增加置信度 */
    entry->pattern.stride_confidence =
        min(entry->pattern.stride_confidence + 5, 100u);

    spin_lock(&g_ra.stats_lock);
    g_ra.stats.correct_predictions++;
    spin_unlock(&g_ra.stats_lock);

    spin_unlock_irqrestore(&entry->lock, flags);
}
EXPORT_SYMBOL_GPL(ai_readahead_confirm);

void ai_readahead_record_batch(const char *filename,
                                unsigned long *offsets, unsigned int count)
{
    unsigned int i;

    for (i = 0; i < count; i++)
        ai_readahead_record(filename, offsets[i]);
}
EXPORT_SYMBOL_GPL(ai_readahead_record_batch);

/// 在 ai_readahead_confirm() 后增加负确认函数
void ai_readahead_confirm_negative(const char *filename, unsigned long offset)
{
    struct ra_entry *entry;
    unsigned long flags;

    if (!filename || !g_ra.initialized)
        return;

    entry = ra_lookup(filename);
    if (!entry)
        return;

    spin_lock_irqsave(&entry->lock, flags);

    /* 预测错误: 降低置信度 */
    if (entry->pattern.stride_confidence >= 10)
        entry->pattern.stride_confidence -= 10;
    else
        entry->pattern.stride_confidence = 0;

    /* 如果连续错误太多，降级为随机模式 */
    if (entry->total_predictions > 5 &&
        entry->correct_predictions * 100 / entry->total_predictions < 30) {
        entry->pattern.model = AI_RA_MODEL_RANDOM;
    }

    spin_lock(&g_ra.stats_lock);
    g_ra.stats.false_predictions++;
    spin_unlock(&g_ra.stats_lock);

    spin_unlock_irqrestore(&entry->lock, flags);
}
EXPORT_SYMBOL_GPL(ai_readahead_confirm_negative);

/// 清除指定文件的跟踪
void ai_readahead_clear_file(const char *filename)
{
    struct ra_entry *entry;
    unsigned long flags;

    if (!filename || !g_ra.initialized)
        return;

    spin_lock_irqsave(&g_ra.lru_lock, flags);
    entry = ra_lookup(filename);
    if (entry && entry->valid) {
        hlist_del(&entry->hash_node);
        list_del(&entry->lru_node);
        entry->valid = false;
        g_ra.entry_count--;
        kfree(entry);
    }
    spin_unlock_irqrestore(&g_ra.lru_lock, flags);
}
EXPORT_SYMBOL_GPL(ai_readahead_clear_file);

void ai_readahead_clear_all(void)
{
    unsigned long flags;
    int i;

    if (!g_ra.initialized)
        return;

    spin_lock_irqsave(&g_ra.lru_lock, flags);

    for (i = 0; i < g_ra.hash_size; i++) {
        struct hlist_node *tmp;
        struct ra_entry *entry;

        hlist_for_each_entry_safe(entry, tmp, &g_ra.hash_table[i], hash_node) {
            hlist_del(&entry->hash_node);
            list_del(&entry->lru_node);
            entry->valid = false;
            kfree(entry);
        }
    }

    g_ra.entry_count = 0;
    INIT_LIST_HEAD(&g_ra.lru_list);

    spin_unlock_irqrestore(&g_ra.lru_lock, flags);

    pr_info("ai-readahead: all tracking data cleared\n");
}
EXPORT_SYMBOL_GPL(ai_readahead_clear_all);

int ai_readahead_get_stats(const char *filename,
                            struct ai_ra_file_stats *stats)
{
    struct ra_entry *entry;
    unsigned long flags;

    if (!filename || !stats || !g_ra.initialized)
        return -EINVAL;

    entry = ra_lookup(filename);
    if (!entry)
        return -ENOENT;

    spin_lock_irqsave(&entry->lock, flags);
    strscpy(stats->name, entry->name, sizeof(stats->name));
    stats->total_accesses = entry->total_accesses;
    stats->sequential_accesses = entry->sequential_accesses;
    stats->random_accesses = entry->random_accesses;
    stats->correct_predictions = entry->correct_predictions;
    stats->total_predictions = entry->total_predictions;

    struct ai_ra_prediction pred = make_prediction(&entry->pattern);
    stats->current_confidence = pred.confidence;
    stats->current_model = entry->pattern.model;
    stats->suggested_window = pred.suggested_window;
    spin_unlock_irqrestore(&entry->lock, flags);

    return 0;
}
EXPORT_SYMBOL_GPL(ai_readahead_get_stats);

void ai_readahead_get_global(struct ai_ra_global_stats *stats)
{
    if (stats && g_ra.initialized) {
        spin_lock(&g_ra.stats_lock);
        *stats = g_ra.stats;
        stats->tracked_files = g_ra.entry_count;

        if (g_ra.stats.total_predictions > 0) {
            stats->avg_confidence = (unsigned int)(
                g_ra.stats.correct_predictions * 100 /
                g_ra.stats.total_predictions);
        }
        spin_unlock(&g_ra.stats_lock);
    }
}
EXPORT_SYMBOL_GPL(ai_readahead_get_global);

/* ================================================================
 * /proc/ai-readahead/status
 * ================================================================ */

static int proc_status_show(struct seq_file *m, void *v)
{
    struct ai_ra_global_stats stats;
    u64 uptime = (jiffies - g_ra.start_jiffies) / HZ;

    ai_readahead_get_global(&stats);

    seq_printf(m, "AI Readahead Predictor v%s\n", AI_READAHEAD_VERSION);
    seq_printf(m, "%-30s = %llu sec\n", "Uptime", uptime);
    seq_printf(m, "%-30s = %u\n", "Tracked Files", stats.tracked_files);
    seq_printf(m, "%-30s = %u\n", "Max Tracked Files", g_ra.entry_max);
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu\n", "Total Predictions", stats.total_predictions);
    seq_printf(m, "%-30s = %llu\n", "Correct Predictions", stats.correct_predictions);
    seq_printf(m, "%-30s = %llu\n", "False Predictions", stats.false_predictions);
    seq_printf(m, "%-30s = %u%%\n", "Avg Confidence", stats.avg_confidence);
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu\n", "Sequential Detected", stats.sequential_detected);
    seq_printf(m, "%-30s = %llu\n", "Strided Detected", stats.strided_detected);
    seq_printf(m, "%-30s = %llu\n", "Random Detected", stats.random_detected);
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %u pages\n", "Seq Window", seq_window);
    seq_printf(m, "%-30s = %u pages\n", "Stride Window", stride_window);
    seq_printf(m, "%-30s = %u pages\n", "Random Window", random_window);

    return 0;
}

static int proc_status_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_status_show, NULL);
}

static const struct proc_ops proc_status_fops = {
    .proc_open    = proc_status_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-readahead/files
 * ================================================================ */

static int proc_files_show(struct seq_file *m, void *v)
{
    unsigned long flags;
    struct ra_entry *entry;
    int count = 0;

    seq_printf(m, "%-8s %-32s %8s %8s %8s %8s %8s\n",
               "Model", "File", "Access", "Seq", "Rand",
               "Conf", "Window");

    spin_lock_irqsave(&g_ra.lru_lock, flags);

    list_for_each_entry_reverse(entry, &g_ra.lru_list, lru_node) {
        if (!entry->valid) continue;
        if (count++ >= 50) break;

        struct ai_ra_prediction pred = make_prediction(&entry->pattern);
        const char *model_name;

        switch (entry->pattern.model) {
        case AI_RA_MODEL_SEQUENTIAL: model_name = "SEQ"; break;
        case AI_RA_MODEL_STRIDED:    model_name = "STR"; break;
        case AI_RA_MODEL_RANDOM:     model_name = "RND"; break;
        case AI_RA_MODEL_SUBPAGE:    model_name = "SUB"; break;
        default:                     model_name = "UNK"; break;
        }

        seq_printf(m, "%-8s %-32s %8llu %8llu %8llu %8u %8u\n",
                   model_name,
                   entry->name,
                   entry->total_accesses,
                   entry->sequential_accesses,
                   entry->random_accesses,
                   pred.confidence,
                   pred.suggested_window);
    }

    seq_printf(m, "\n%d files displayed (%u total tracked)\n",
               count, g_ra.entry_count);

    spin_unlock_irqrestore(&g_ra.lru_lock, flags);
    return 0;
}

static int proc_files_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_files_show, NULL);
}

static const struct proc_ops proc_files_fops = {
    .proc_open    = proc_files_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * /proc/ai-readahead/config
 * ================================================================ */

static int proc_config_show(struct seq_file *m, void *v)
{
    seq_printf(m, "%-24s = %u\n", "max_tracked_files", g_ra.entry_max);
    seq_printf(m, "%-24s = %u\n", "max_confidence", max_confidence);
    seq_printf(m, "%-24s = %u pages\n", "seq_window", seq_window);
    seq_printf(m, "%-24s = %u pages\n", "stride_window", stride_window);
    seq_printf(m, "%-24s = %u pages\n", "random_window", random_window);
    return 0;
}

static int proc_config_open(struct inode *inode, struct file *file)
{
    return single_open(file, proc_config_show, NULL);
}

static ssize_t proc_config_write(struct file *file,
                                  const char __user *ubuf,
                                  size_t count, loff_t *ppos)
{
    char buf[128];
    char cmd[32];
    unsigned int val;

    if (count >= sizeof(buf))
        return -EINVAL;

    if (copy_from_user(buf, ubuf, count))
        return -EFAULT;
    buf[count] = '\0';
    if (count > 0 && buf[count - 1] == '\n')
        buf[count - 1] = '\0';

    if (sscanf(buf, "%31s %u", cmd, &val) != 2)
        return -EINVAL;

    if (strcmp(cmd, "seq_window") == 0)
        seq_window = val;
    else if (strcmp(cmd, "stride_window") == 0)
        stride_window = val;
    else if (strcmp(cmd, "random_window") == 0)
        random_window = val;
    else if (strcmp(cmd, "max_confidence") == 0)
        max_confidence = min(val, 100u);
    else if (strcmp(cmd, "clear") == 0)
        ai_readahead_clear_all();
    else
        return -EINVAL;

    return count;
}

static const struct proc_ops proc_config_fops = {
    .proc_open    = proc_config_open,
    .proc_read    = seq_read,
    .proc_write   = proc_config_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * 初始化
 * ================================================================ */

static int __init ai_readahead_init(void)
{
    int i;

    pr_info("ai-readahead: Ainos AI Readahead v%s initializing...\n",
            AI_READAHEAD_VERSION);

    memset(&g_ra, 0, sizeof(g_ra));
    g_ra.hash_size = hash_size;
    g_ra.entry_max = hash_size;
    g_ra.entry_count = 0;
    g_ra.start_jiffies = jiffies;

    /* 分配 hash 表 */
    g_ra.hash_table = kcalloc(hash_size, sizeof(struct hlist_head), GFP_KERNEL);
    if (!g_ra.hash_table) {
        pr_err("ai-readahead: failed to allocate hash table\n");
        return -ENOMEM;
    }

    for (i = 0; i < hash_size; i++)
        INIT_HLIST_HEAD(&g_ra.hash_table[i]);

    /* 初始化 LRU */
    INIT_LIST_HEAD(&g_ra.lru_list);
    spin_lock_init(&g_ra.lru_lock);
    spin_lock_init(&g_ra.stats_lock);

    /* 创建 /proc/ai-readahead */
    g_ra.proc_dir = proc_mkdir("ai-readahead", NULL);
    if (!g_ra.proc_dir) {
        pr_err("ai-readahead: failed to create /proc/ai-readahead\n");
        kfree(g_ra.hash_table);
        return -ENOMEM;
    }

    g_ra.proc_status = proc_create("status", 0444, g_ra.proc_dir,
                                    &proc_status_fops);
    g_ra.proc_files = proc_create("files", 0444, g_ra.proc_dir,
                                   &proc_files_fops);
    g_ra.proc_config = proc_create("config", 0644, g_ra.proc_dir,
                                    &proc_config_fops);

    if (!g_ra.proc_status || !g_ra.proc_files || !g_ra.proc_config) {
        pr_err("ai-readahead: failed to create proc files\n");
        if (g_ra.proc_config) remove_proc_entry("config", g_ra.proc_dir);
        if (g_ra.proc_files)  remove_proc_entry("files", g_ra.proc_dir);
        if (g_ra.proc_status) remove_proc_entry("status", g_ra.proc_dir);
        remove_proc_entry("ai-readahead", NULL);
        kfree(g_ra.hash_table);
        return -ENOMEM;
    }

    g_ra.initialized = true;

    pr_info("ai-readahead: AI Readahead v%s initialized\n", AI_READAHEAD_VERSION);
    pr_info("ai-readahead: hash=%u entries, max=%u tracked files\n",
            hash_size, g_ra.entry_max);
    pr_info("ai-readahead: /proc/ai-readahead/{status,files,config}\n");

    return 0;
}

/* ================================================================
 * 清理
 * ================================================================ */

static void __exit ai_readahead_exit(void)
{
    if (!g_ra.initialized)
        return;

    pr_info("ai-readahead: shutting down...\n");

    g_ra.initialized = false;

    /* 清理所有跟踪数据 */
    ai_readahead_clear_all();

    /* 清理 proc 文件 */
    if (g_ra.proc_config) remove_proc_entry("config", g_ra.proc_dir);
    if (g_ra.proc_files)  remove_proc_entry("files", g_ra.proc_dir);
    if (g_ra.proc_status) remove_proc_entry("status", g_ra.proc_dir);
    if (g_ra.proc_dir)    remove_proc_entry("ai-readahead", NULL);

    /* 释放 hash 表 */
    kfree(g_ra.hash_table);

    pr_info("ai-readahead: unloaded\n");
}

module_init(ai_readahead_init);
module_exit(ai_readahead_exit);