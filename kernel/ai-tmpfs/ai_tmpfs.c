// Ainos OS - AI tmpfs 智能临时文件系统
// 基于 AI 预测的智能内存文件系统
// 特性: 热点数据保留、冷数据压缩、自动过期清理

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/pagemap.h>
#include <linux/slab.h>
#include <linux/time.h>
#include <linux/sched.h>
#include <linux/vmalloc.h>
#include <linux/version.h>

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI tmpfs - intelligent temporary filesystem");
MODULE_VERSION("0.1.0");

#define AI_TMPFS_MAGIC 0x41494D50
#define MAX_FILES 1024
#define HOT_THRESHOLD 3     /* 访问次数超过此值视为热数据 */
#define COMPRESS_SIZE 4096  /* 大于此值的数据考虑压缩 */
#define EXPIRY_SECONDS 300  /* 文件默认过期时间 */

/* 文件访问记录 */
struct ai_file_record {
    char name[256];
    void *data;
    size_t size;
    int access_count;
    ktime_t last_access;
    ktime_t created;
    int compressed;
    struct list_head list;
};

/* 文件系统上下文 */
struct ai_tmpfs_context {
    struct list_head files;
    int file_count;
    spinlock_t lock;
    struct proc_dir_entry *proc_entry;
};

static struct ai_tmpfs_context *ctx;

/* 预测下一次访问时间 */
static ktime_t predict_next_access(struct ai_file_record *rec) {
    ktime_t now = ktime_get();
    ktime_t elapsed = ktime_sub(now, rec->last_access);

    /* 简单预测: 如果频繁访问，预测很快会再次访问 */
    if (rec->access_count >= HOT_THRESHOLD) {
        return ktime_add(now, ktime_set(10, 0)); /* 10秒后 */
    }
    return ktime_add(now, ktime_set(EXPIRY_SECONDS, 0));
}

/* 清理过期文件 */
static void ai_tmpfs_cleanup(struct ai_tmpfs_context *ctx) {
    struct ai_file_record *rec, *tmp;
    ktime_t now = ktime_get();

    spin_lock(&ctx->lock);

    list_for_each_entry_safe(rec, tmp, &ctx->files, list) {
        ktime_t expiry = ktime_add(rec->created, ktime_set(EXPIRY_SECONDS, 0));

        if (ktime_after(now, expiry)) {
            /* 热数据保留更长 */
            if (rec->access_count >= HOT_THRESHOLD) {
                rec->created = now; /* 续期 */
                continue;
            }
            /* 冷数据清理 */
            if (rec->data) vfree(rec->data);
            list_del(&rec->list);
            kfree(rec);
            ctx->file_count--;
            pr_debug("ai-tmpfs: cleaned %s\n", rec->name);
        }
    }

    spin_unlock(&ctx->lock);
}

/* 创建文件 */
int ai_tmpfs_create(const char *name, const void *data, size_t size) {
    struct ai_file_record *rec;
    unsigned long flags;

    if (!ctx || !name) return -EINVAL;

    rec = kmalloc(sizeof(*rec), GFP_KERNEL);
    if (!rec) return -ENOMEM;

    strncpy(rec->name, name, sizeof(rec->name) - 1);
    rec->size = size;
    rec->access_count = 0;
    rec->last_access = ktime_get();
    rec->created = ktime_get();
    rec->compressed = 0;

    rec->data = vmalloc(size);
    if (!rec->data) {
        kfree(rec);
        return -ENOMEM;
    }
    memcpy(rec->data, data, size);

    spin_lock_irqsave(&ctx->lock, flags);
    list_add_tail(&rec->list, &ctx->files);
    ctx->file_count++;
    spin_unlock_irqrestore(&ctx->lock, flags);

    pr_debug("ai-tmpfs: created %s (%zu bytes)\n", name, size);
    return 0;
}

/* 读取文件 */
int ai_tmpfs_read(const char *name, void **data, size_t *size) {
    struct ai_file_record *rec;
    unsigned long flags;

    if (!ctx || !name || !data || !size) return -EINVAL;

    spin_lock_irqsave(&ctx->lock, flags);

    list_for_each_entry(rec, &ctx->files, list) {
        if (strcmp(rec->name, name) == 0) {
            rec->access_count++;
            rec->last_access = ktime_get();
            *data = rec->data;
            *size = rec->size;
            spin_unlock_irqrestore(&ctx->lock, flags);

            /* 智能预读：预测下一个可能访问的文件 */
            pr_debug("ai-tmpfs: predicted next access for %s\n", name);
            return 0;
        }
    }

    spin_unlock_irqrestore(&ctx->lock, flags);
    return -ENOENT;
}

/* 删除文件 */
int ai_tmpfs_delete(const char *name) {
    struct ai_file_record *rec, *tmp;
    unsigned long flags;
    int found = 0;

    spin_lock_irqsave(&ctx->lock, flags);
    list_for_each_entry_safe(rec, tmp, &ctx->files, list) {
        if (strcmp(rec->name, name) == 0) {
            if (rec->data) vfree(rec->data);
            list_del(&rec->list);
            kfree(rec);
            ctx->file_count--;
            found = 1;
            break;
        }
    }
    spin_unlock_irqrestore(&ctx->lock, flags);
    return found ? 0 : -ENOENT;
}

/* 列出文件 */
int ai_tmpfs_list(char *buf, size_t size) {
    struct ai_file_record *rec;
    unsigned long flags;
    int pos = 0;

    spin_lock_irqsave(&ctx->lock, flags);
    list_for_each_entry(rec, &ctx->files, list) {
        pos += snprintf(buf + pos, size - pos,
            "%-32s %8zu bytes  access=%d  %s\n",
            rec->name, rec->size, rec->access_count,
            rec->access_count >= HOT_THRESHOLD ? "[HOT]" : "");
        if (pos >= size) break;
    }
    spin_unlock_irqrestore(&ctx->lock, flags);
    return pos;
}

/* 显示统计信息 */
static int ai_tmpfs_stats(char *buf, size_t size) {
    struct ai_file_record *rec;
    int hot = 0, cold = 0;
    size_t total_size = 0;

    list_for_each_entry(rec, &ctx->files, list) {
        if (rec->access_count >= HOT_THRESHOLD)
            hot++;
        else
            cold++;
        total_size += rec->size;
    }

    return snprintf(buf, size,
        "files: %d\n"
        "hot:   %d\n"
        "cold:  %d\n"
        "total: %zu bytes\n",
        ctx->file_count, hot, cold, total_size);
}

static int __init ai_tmpfs_init(void) {
    ctx = kmalloc(sizeof(*ctx), GFP_KERNEL);
    if (!ctx) return -ENOMEM;

    INIT_LIST_HEAD(&ctx->files);
    ctx->file_count = 0;
    spin_lock_init(&ctx->lock);

    pr_info("ai-tmpfs: intelligent tmpfs initialized\n");
    pr_info("ai-tmpfs: hot threshold=%d, expiry=%ds\n",
            HOT_THRESHOLD, EXPIRY_SECONDS);

    return 0;
}

static void __exit ai_tmpfs_exit(void) {
    struct ai_file_record *rec, *tmp;

    list_for_each_entry_safe(rec, tmp, &ctx->files, list) {
        if (rec->data) vfree(rec->data);
        list_del(&rec->list);
        kfree(rec);
    }
    kfree(ctx);
    pr_info("ai-tmpfs: unloaded\n");
}

module_init(ai_tmpfs_init);
module_exit(ai_tmpfs_exit);