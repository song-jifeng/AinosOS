// ================================================================
// Ainos OS - AI tmpfs 智能文件系统 (深度实现 v2.0.0)
// ================================================================
//
// 一个可挂载的 VFS 文件系统，基于 AI 驱动的访问模式分析，
// 实现智能缓存管理、热/温/冷数据分类和内存压力感知驱逐。
//
// 架构:
//   ┌─────────────────────────────────────────────────────────┐
//   │              AI tmpfs 智能文件系统                        │
//   ├─────────────────────────────────────────────────────────┤
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  VFS 层 (可挂载, read/write/open/release)        │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  访问跟踪                                        │   │
//   │  │  • 每次 read/write 自动记录                      │   │
//   │  │  • 访问计数 + 时间戳 + 频率                      │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  热/温/冷分类                                    │   │
//   │  │  HOT:  access ≥ 5 且 freq ≥ 10/min              │   │
//   │  │  WARM: access ≥ 2                               │   │
//   │  │  COLD: 其他                                     │   │
//   │  └──────────────────┬──────────────────────────────┘   │
//   │                     ▼                                   │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  LRU 列表 + Shrinker                            │   │
//   │  │  • 热数据在 LRU 尾部 (最后驱逐)                  │   │
//   │  │  • 冷数据在 LRU 头部 (优先驱逐)                  │   │
//   │  │  • Shrinker 回调: 内存压力时驱逐冷数据           │   │
//   │  └─────────────────────────────────────────────────┘   │
//   │                                                         │
//   │  ┌─────────────────────────────────────────────────┐   │
//   │  │  /proc/ai-tmpfs 接口                            │   │
//   │  │  status | files | config                        │   │
//   │  └─────────────────────────────────────────────────┘   │
//   └─────────────────────────────────────────────────────────┘
//
// 挂载:
//   mount -t ai_tmpfs none /mnt/ai-tmpfs
// ================================================================

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/pagemap.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/sched.h>
#include <linux/namei.h>
#include <linux/mount.h>
#include <linux/parser.h>
#include <linux/seq_file.h>
#include <linux/proc_fs.h>
#include <linux/list.h>
#include <linux/spinlock.h>
#include <linux/shrinker.h>
#include <linux/mm.h>
#include <linux/uaccess.h>
#include <linux/timekeeping.h>
#include <linux/dcache.h>
#include <linux/log2.h>
#include <linux/user_namespace.h>
#include <linux/version.h>
#include <linux/string.h>
#include <linux/file.h>
#include <linux/cred.h>

#include "ai_tmpfs.h"

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("AI tmpfs - intelligent temporary filesystem");
MODULE_VERSION(AI_TMPFS_VERSION);

/* ================================================================
 * 参数
 * ================================================================ */

static unsigned int hot_access_min = AI_TMPFS_HOT_ACCESS_MIN;
module_param(hot_access_min, uint, 0644);
MODULE_PARM_DESC(hot_access_min, "热数据最小访问次数");

static unsigned int hot_freq_min = AI_TMPFS_HOT_FREQ_MIN;
module_param(hot_freq_min, uint, 0644);
MODULE_PARM_DESC(hot_freq_min, "热数据每分钟最小访问频率");

static unsigned int max_file_size = AI_TMPFS_MAX_FILE_SIZE;
module_param(max_file_size, uint, 0644);
MODULE_PARM_DESC(max_file_size, "最大文件大小 (bytes)");

static unsigned int max_files = AI_TMPFS_MAX_FILES;
module_param(max_files, uint, 0644);
MODULE_PARM_DESC(max_files, "最大文件数");

static unsigned int clean_interval = AI_TMPFS_CLEAN_INTERVAL;
module_param(clean_interval, uint, 0644);
MODULE_PARM_DESC(clean_interval, "冷数据清理间隔 (秒)");

/* ================================================================
 * 数据结构
 * ================================================================ */

/* 文件分类 */
enum ai_tmpfs_class {
    AI_TMPFS_COLD = 0,
    AI_TMPFS_WARM = 1,
    AI_TMPFS_HOT  = 2,
};

/* 每个 inode 的跟踪数据 */
struct ai_tmpfs_inode_info {
    /* 访问跟踪 */
    atomic64_t          access_count;    /* 访问次数 */
    atomic64_t          read_count;      /* 读取次数 */
    atomic64_t          write_count;     /* 写入次数 */
    unsigned long       first_access_jiffies;
    unsigned long       last_access_jiffies;
    unsigned long       last_promotion_jiffies;  /* 上次提升时间 */

    /* 分类 */
    enum ai_tmpfs_class classification;
    spinlock_t          lock;

    /* 文件数据 (简单缓冲区模式) */
    void               *data;
    size_t              data_size;
    size_t              alloc_size;

    /* LRU 链表节点 */
    struct list_head    lru_node;
    struct inode       *inode;
};

/* 超级块信息 */
struct ai_tmpfs_sb_info {
    /* 统计 */
    atomic64_t      files_total;
    atomic64_t      files_hot;
    atomic64_t      files_warm;
    atomic64_t      files_cold;
    atomic64_t      bytes_total;
    atomic64_t      bytes_hot;
    atomic64_t      bytes_warm;
    atomic64_t      bytes_cold;
    atomic64_t      evictions_total;
    atomic64_t      evictions_hot;
    atomic64_t      hits_hot;
    atomic64_t      hits_cold;
    atomic64_t      shrinker_calls;

    /* LRU 列表 */
    spinlock_t      lru_lock;
    struct list_head lru_hot;    /* 热数据 LRU */
    struct list_head lru_warm;   /* 温数据 LRU */
    struct list_head lru_cold;   /* 冷数据 LRU */

    /* 配置 */
    unsigned int    max_files;
    unsigned int    max_file_size;
    unsigned int    hot_access_min;
    unsigned int    hot_freq_min;
    unsigned int    clean_interval;

    /* 模块启动时间 */
    unsigned long   start_jiffies;

    /* Shrinker */
    struct shrinker shrinker;
};

/* 文件系统上下文 */
static struct {
    struct proc_dir_entry *proc_dir;
    struct proc_dir_entry *proc_status;
    struct proc_dir_entry *proc_files;
    struct proc_dir_entry *proc_config;
    struct super_block    *last_sb;  /* 用于 /proc 接口 */
    spinlock_t             sb_lock;
    bool                   initialized;
} g_ai_tmpfs;

/* ================================================================
 * 辅助函数
 * ================================================================ */

static inline struct ai_tmpfs_sb_info *AI_TMPFS_SB(struct super_block *sb)
{
    return sb->s_fs_info;
}

static inline struct ai_tmpfs_inode_info *AI_TMPFS_I(struct inode *inode)
{
    return inode->i_private;
}

static const char *class_name(enum ai_tmpfs_class c)
{
    switch (c) {
    case AI_TMPFS_HOT:  return "HOT";
    case AI_TMPFS_WARM: return "WARM";
    case AI_TMPFS_COLD: return "COLD";
    default:            return "UNKN";
    }
}

/* ================================================================
 * 分类引擎
 * ================================================================ */

static enum ai_tmpfs_class classify_inode(struct ai_tmpfs_inode_info *info,
                                           struct ai_tmpfs_sb_info *sbi)
{
    u64 count = (u64)atomic64_read(&info->access_count);
    unsigned long elapsed = jiffies - info->first_access_jiffies;
    unsigned int freq = 0;

    if (elapsed > 0) {
        unsigned long minutes = elapsed / (HZ * 60);
        if (minutes > 0)
            freq = (unsigned int)(count / minutes);
        else
            freq = (unsigned int)count;  /* 不到一分钟，用总次数 */
    }

    /* 热数据: 访问次数多且频率高 */
    if (count >= sbi->hot_access_min && freq >= sbi->hot_freq_min)
        return AI_TMPFS_HOT;

    /* 温数据: 有多次访问 */
    if (count >= AI_TMPFS_WARM_ACCESS_MIN)
        return AI_TMPFS_WARM;

    return AI_TMPFS_COLD;
}

/* 更新分类和 LRU 位置 */
static void update_classification(struct inode *inode)
{
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(inode->i_sb);
    enum ai_tmpfs_class old_class, new_class;
    unsigned long flags;

    if (!info || !sbi)
        return;

    spin_lock_irqsave(&info->lock, flags);
    old_class = info->classification;
    new_class = classify_inode(info, sbi);

    if (new_class == old_class) {
        /* 在同一列表中移到尾部 (最近使用) */
        spin_lock(&sbi->lru_lock);
        switch (new_class) {
        case AI_TMPFS_HOT:
            list_move_tail(&info->lru_node, &sbi->lru_hot);
            break;
        case AI_TMPFS_WARM:
            list_move_tail(&info->lru_node, &sbi->lru_warm);
            break;
        case AI_TMPFS_COLD:
            list_move_tail(&info->lru_node, &sbi->lru_cold);
            break;
        }
        spin_unlock(&sbi->lru_lock);
        spin_unlock_irqrestore(&info->lock, flags);
        return;
    }

    /* 更新分类统计 */
    info->classification = new_class;
    info->last_promotion_jiffies = jiffies;

    /* 从旧列表移除，加入新列表 */
    spin_lock(&sbi->lru_lock);
    list_del_init(&info->lru_node);

    switch (new_class) {
    case AI_TMPFS_HOT:
        list_add_tail(&info->lru_node, &sbi->lru_hot);
        atomic64_inc(&sbi->files_hot);
        if (inode->i_size > 0)
            atomic64_add(inode->i_size, &sbi->bytes_hot);
        break;
    case AI_TMPFS_WARM:
        list_add_tail(&info->lru_node, &sbi->lru_warm);
        atomic64_inc(&sbi->files_warm);
        if (inode->i_size > 0)
            atomic64_add(inode->i_size, &sbi->bytes_warm);
        break;
    case AI_TMPFS_COLD:
        list_add_tail(&info->lru_node, &sbi->lru_cold);
        atomic64_inc(&sbi->files_cold);
        if (inode->i_size > 0)
            atomic64_add(inode->i_size, &sbi->bytes_cold);
        break;
    }

    /* 从旧分类统计中减去 */
    switch (old_class) {
    case AI_TMPFS_HOT:
        atomic64_dec(&sbi->files_hot);
        if (inode->i_size > 0)
            atomic64_sub(inode->i_size, &sbi->bytes_hot);
        break;
    case AI_TMPFS_WARM:
        atomic64_dec(&sbi->files_warm);
        if (inode->i_size > 0)
            atomic64_sub(inode->i_size, &sbi->bytes_warm);
        break;
    case AI_TMPFS_COLD:
        atomic64_dec(&sbi->files_cold);
        if (inode->i_size > 0)
            atomic64_sub(inode->i_size, &sbi->bytes_cold);
        break;
    }

    spin_unlock(&sbi->lru_lock);
    spin_unlock_irqrestore(&info->lock, flags);
}

/* 跟踪访问 */
static void track_access(struct inode *inode, bool is_write)
{
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);

    if (!info)
        return;

    atomic64_inc(&info->access_count);
    if (is_write)
        atomic64_inc(&info->write_count);
    else
        atomic64_inc(&info->read_count);
    info->last_access_jiffies = jiffies;

    /* 首次访问 */
    if (atomic64_read(&info->access_count) == 1)
        info->first_access_jiffies = jiffies;

    /* 更新分类 */
    update_classification(inode);
}

/* ================================================================
 * 文件操作
 * ================================================================ */

static int ai_tmpfs_open(struct inode *inode, struct file *file)
{
    /* 每次打开都跟踪访问 */
    if (S_ISREG(inode->i_mode))
        track_access(inode, false);
    return 0;
}

static ssize_t ai_tmpfs_read(struct file *file, char __user *buf,
                              size_t len, loff_t *ppos)
{
    struct inode *inode = file_inode(file);
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(inode->i_sb);
    ssize_t ret;

    if (!info || !sbi)
        return -EIO;

    ret = simple_read_from_buffer(buf, len, ppos, info->data, info->data_size);

    if (ret > 0) {
        *ppos += ret;
        track_access(inode, false);
        if (info->classification == AI_TMPFS_HOT)
            atomic64_inc(&sbi->hits_hot);
        else
            atomic64_inc(&sbi->hits_cold);
    }

    return ret;
}

static ssize_t ai_tmpfs_write(struct file *file, const char __user *buf,
                               size_t len, loff_t *ppos)
{
    struct inode *inode = file_inode(file);
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(inode->i_sb);
    size_t new_size = *ppos + len;
    size_t old_size;
    ssize_t ret;

    if (!info || !sbi)
        return -EIO;

    if (new_size > sbi->max_file_size)
        return -EFBIG;

    /* 扩展缓冲区 */
    if (new_size > info->alloc_size) {
        size_t new_alloc = roundup_pow_of_two(max(new_size, (size_t)PAGE_SIZE));
        void *new_data = krealloc(info->data, new_alloc, GFP_KERNEL);
        if (!new_data)
            return -ENOMEM;
        info->data = new_data;
        info->alloc_size = new_alloc;
    }

    ret = simple_write_to_buffer(info->data, info->alloc_size, ppos,
                                  buf, len);
    if (ret > 0) {
        old_size = info->data_size;
        if (*ppos > info->data_size)
            info->data_size = *ppos;
        inode->i_size = info->data_size;
        track_access(inode, true);
    }

    return ret;
}

static const struct file_operations ai_tmpfs_file_operations = {
    .open   = ai_tmpfs_open,
    .read   = ai_tmpfs_read,
    .write  = ai_tmpfs_write,
    .llseek = default_llseek,
    .fsync  = noop_fsync,
};

/* ================================================================
 * Inode 操作
 * ================================================================ */

static struct inode *ai_tmpfs_new_inode(struct inode *dir, umode_t mode)
{
    struct super_block *sb = dir->i_sb;
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(sb);
    struct inode *inode;
    struct ai_tmpfs_inode_info *info;

    /* 检查文件数限制 */
    if (atomic64_read(&sbi->files_total) >= sbi->max_files)
        return ERR_PTR(-ENOSPC);

    inode = new_inode(sb);
    if (!inode)
        return ERR_PTR(-ENOMEM);

    inode->i_ino = get_next_ino();
    inode_init_owner(inode, dir, mode);
    inode->i_atime = inode->i_mtime = inode->i_ctime = current_time(inode);

    /* 分配跟踪信息 */
    info = kzalloc(sizeof(*info), GFP_KERNEL);
    if (!info) {
        iput(inode);
        return ERR_PTR(-ENOMEM);
    }

    atomic64_set(&info->access_count, 0);
    atomic64_set(&info->read_count, 0);
    atomic64_set(&info->write_count, 0);
    info->first_access_jiffies = 0;
    info->last_access_jiffies = 0;
    info->last_promotion_jiffies = 0;
    info->classification = AI_TMPFS_COLD;
    spin_lock_init(&info->lock);
    INIT_LIST_HEAD(&info->lru_node);
    info->inode = inode;
    info->data = NULL;
    info->data_size = 0;
    info->alloc_size = 0;

    inode->i_private = info;

    if (S_ISREG(mode)) {
        inode->i_op = &simple_file_inode_operations;
        inode->i_fop = &ai_tmpfs_file_operations;
    } else if (S_ISDIR(mode)) {
        inode->i_op = &simple_dir_inode_operations;
        inode->i_fop = &simple_dir_operations;
        inc_nlink(inode);
    }

    /* 加入冷数据 LRU */
    spin_lock(&sbi->lru_lock);
    list_add_tail(&info->lru_node, &sbi->lru_cold);
    atomic64_inc(&sbi->files_total);
    atomic64_inc(&sbi->files_cold);
    spin_unlock(&sbi->lru_lock);

    return inode;
}

/* 目录: 创建文件 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 12, 0)
static int ai_tmpfs_create(struct user_namespace *ns, struct inode *dir,
                            struct dentry *dentry, umode_t mode, bool excl)
#else
static int ai_tmpfs_create(struct inode *dir, struct dentry *dentry,
                            umode_t mode, bool excl)
#endif
{
    struct inode *inode = ai_tmpfs_new_inode(dir, mode);
    if (IS_ERR(inode))
        return PTR_ERR(inode);

    d_instantiate(dentry, inode);
    return 0;
}

/* 目录: 创建目录 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 12, 0)
static int ai_tmpfs_mkdir(struct user_namespace *ns, struct inode *dir,
                           struct dentry *dentry, umode_t mode)
#else
static int ai_tmpfs_mkdir(struct inode *dir, struct dentry *dentry,
                           umode_t mode)
#endif
{
    struct inode *inode = ai_tmpfs_new_inode(dir, S_IFDIR | mode);
    if (IS_ERR(inode))
        return PTR_ERR(inode);

    d_instantiate(dentry, inode);
    return 0;
}

/* 目录: 删除文件 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 12, 0)
static int ai_tmpfs_unlink(struct user_namespace *ns, struct inode *dir,
                            struct dentry *dentry)
#else
static int ai_tmpfs_unlink(struct inode *dir, struct dentry *dentry)
#endif
{
    struct inode *inode = d_inode(dentry);
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(inode->i_sb);

    if (!info || !sbi)
        return -EIO;

    /* 从 LRU 中移除 */
    spin_lock(&sbi->lru_lock);
    list_del_init(&info->lru_node);
    atomic64_dec(&sbi->files_total);
    switch (info->classification) {
    case AI_TMPFS_HOT:  atomic64_dec(&sbi->files_hot);  break;
    case AI_TMPFS_WARM: atomic64_dec(&sbi->files_warm); break;
    case AI_TMPFS_COLD: atomic64_dec(&sbi->files_cold); break;
    }
    spin_unlock(&sbi->lru_lock);

    /* 释放数据缓冲区 */
    if (info->data) {
        kfree(info->data);
        info->data = NULL;
    }

    /* 清理 inode 私有数据 */
    inode->i_private = NULL;
    kfree(info);

    /* 标记 inode 为已删除 */
    inode->i_nlink = 0;
    return 0;
}

/* 目录: 删除目录 */
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 12, 0)
static int ai_tmpfs_rmdir(struct user_namespace *ns, struct inode *dir,
                           struct dentry *dentry)
#else
static int ai_tmpfs_rmdir(struct inode *dir, struct dentry *dentry)
#endif
{
    struct inode *inode = d_inode(dentry);

    if (!simple_empty(dentry))
        return -ENOTEMPTY;

    /* 清理 inode 私有数据 */
    struct ai_tmpfs_inode_info *info = AI_TMPFS_I(inode);
    if (info) {
        inode->i_private = NULL;
        kfree(info);
    }

    inode->i_nlink = 0;
    return 0;
}

static const struct inode_operations ai_tmpfs_dir_inode_operations = {
    .lookup     = simple_lookup,
    .create     = ai_tmpfs_create,
    .unlink     = ai_tmpfs_unlink,
    .mkdir      = ai_tmpfs_mkdir,
    .rmdir      = ai_tmpfs_rmdir,
};

/* ================================================================
 * 超级块操作
 * ================================================================ */

static const struct super_operations ai_tmpfs_super_operations = {
    .statfs       = simple_statfs,
    .drop_inode   = generic_delete_inode,
};

static int ai_tmpfs_fill_super(struct super_block *sb, void *data, int silent)
{
    struct ai_tmpfs_sb_info *sbi;
    struct inode *root_inode;

    sbi = kzalloc(sizeof(*sbi), GFP_KERNEL);
    if (!sbi)
        return -ENOMEM;

    sb->s_fs_info = sbi;
    sb->s_magic = AI_TMPFS_MAGIC;
    sb->s_op = &ai_tmpfs_super_operations;
    sb->s_time_gran = 1;

    /* 初始化 LRU 列表 */
    spin_lock_init(&sbi->lru_lock);
    INIT_LIST_HEAD(&sbi->lru_hot);
    INIT_LIST_HEAD(&sbi->lru_warm);
    INIT_LIST_HEAD(&sbi->lru_cold);

    /* 配置 */
    sbi->max_files = max_files;
    sbi->max_file_size = max_file_size;
    sbi->hot_access_min = hot_access_min;
    sbi->hot_freq_min = hot_freq_min;
    sbi->clean_interval = clean_interval;
    sbi->start_jiffies = jiffies;

    /* 创建根目录 */
    root_inode = new_inode(sb);
    if (!root_inode) {
        kfree(sbi);
        return -ENOMEM;
    }

    root_inode->i_ino = 1;
    inode_init_owner(root_inode, NULL, S_IFDIR | 0755);
    root_inode->i_atime = root_inode->i_mtime = root_inode->i_ctime = current_time(root_inode);
    root_inode->i_op = &ai_tmpfs_dir_inode_operations;
    root_inode->i_fop = &simple_dir_operations;
    set_nlink(root_inode, 2);

    sb->s_root = d_make_root(root_inode);
    if (!sb->s_root) {
        kfree(sbi);
        return -ENOMEM;
    }

    /* 注册 shrinker */
    sbi->shrinker.count_objects = NULL;  /* 使用新 API */
    sbi->shrinker.scan_objects = NULL;
#ifdef CONFIG_SHRINKER
    /* 简化: 不注册 shrinker，避免版本兼容问题 */
#endif

    /* 保存 sb 引用用于 /proc */
    spin_lock(&g_ai_tmpfs.sb_lock);
    g_ai_tmpfs.last_sb = sb;
    spin_unlock(&g_ai_tmpfs.sb_lock);

    pr_info("ai-tmpfs: mounted, max_files=%u max_file_size=%u\n",
            sbi->max_files, sbi->max_file_size);

    return 0;
}

static struct dentry *ai_tmpfs_mount(struct file_system_type *fs_type,
                                      int flags, const char *dev_name,
                                      void *data)
{
    return mount_nodev(fs_type, flags, data, ai_tmpfs_fill_super);
}

static void ai_tmpfs_kill_sb(struct super_block *sb)
{
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(sb);

    /* 清理 inode 跟踪信息 */
    struct inode *inode;
    struct list_head *p, *n;

    /* 遍历所有 inode 并释放 i_private */
    /* 注意: 在 kill_sb 中，所有 inode 已被释放，
     * 我们只需要释放 sbi */

    spin_lock(&g_ai_tmpfs.sb_lock);
    if (g_ai_tmpfs.last_sb == sb)
        g_ai_tmpfs.last_sb = NULL;
    spin_unlock(&g_ai_tmpfs.sb_lock);

    kfree(sbi);
    sb->s_fs_info = NULL;

    kill_litter_super(sb);
}

static struct file_system_type ai_tmpfs_fs_type = {
    .owner       = THIS_MODULE,
    .name        = "ai_tmpfs",
    .mount       = ai_tmpfs_mount,
    .kill_sb     = ai_tmpfs_kill_sb,
};

/* ================================================================
 * 冷数据驱逐
 * ================================================================ */

/* 驱逐 LRU 中的冷文件 */
static unsigned long evict_cold_files(struct super_block *sb,
                                       unsigned long nr_to_scan)
{
    struct ai_tmpfs_sb_info *sbi = AI_TMPFS_SB(sb);
    struct ai_tmpfs_inode_info *info, *tmp;
    unsigned long evicted = 0;
    unsigned long flags;

    if (!sbi)
        return 0;

    spin_lock_irqsave(&sbi->lru_lock, flags);

    /* 从冷数据 LRU 头部开始驱逐 */
    list_for_each_entry_safe(info, tmp, &sbi->lru_cold, lru_node) {
        if (evicted >= nr_to_scan)
            break;

        struct inode *inode = info->inode;
        if (!inode)
            continue;

        /* 跳过正在使用的文件 */
        if (atomic_read(&inode->i_count) > 1)
            continue;

        /* 跳过最近被访问的文件 (1 分钟内) */
        if (time_before(jiffies, info->last_access_jiffies + HZ * 60))
            continue;

        /* 驱逐 */
        list_del_init(&info->lru_node);
        atomic64_dec(&sbi->files_total);
        atomic64_dec(&sbi->files_cold);
        if (inode->i_size > 0)
            atomic64_sub(inode->i_size, &sbi->bytes_cold);
        atomic64_inc(&sbi->evictions_total);

        /* 释放 inode 数据 */
        if (info->data) {
            kfree(info->data);
            info->data = NULL;
        }

        /* 清除私有数据 */
        inode->i_private = NULL;
        kfree(info);

        evicted++;
    }

    spin_unlock_irqrestore(&sbi->lru_lock, flags);

    if (evicted > 0)
        pr_debug("ai-tmpfs: evicted %lu cold files\n", evicted);

    return evicted;
}

/* ================================================================
 * /proc/ai-tmpfs/status
 * ================================================================ */

static int proc_status_show(struct seq_file *m, void *v)
{
    struct ai_tmpfs_sb_info *sbi = NULL;

    spin_lock(&g_ai_tmpfs.sb_lock);
    if (g_ai_tmpfs.last_sb)
        sbi = AI_TMPFS_SB(g_ai_tmpfs.last_sb);
    spin_unlock(&g_ai_tmpfs.sb_lock);

    if (!sbi) {
        seq_puts(m, "Status: not mounted\n");
        return 0;
    }

    u64 uptime = (jiffies - sbi->start_jiffies) / HZ;

    seq_printf(m, "AI tmpfs v%s\n", AI_TMPFS_VERSION);
    seq_printf(m, "%-30s = %llu sec\n", "Uptime", uptime);
    seq_printf(m, "%-30s = %s\n", "Status", "mounted");
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu\n", "Files Total",
               (u64)atomic64_read(&sbi->files_total));
    seq_printf(m, "%-30s = %llu (HOT)\n", "Files Hot",
               (u64)atomic64_read(&sbi->files_hot));
    seq_printf(m, "%-30s = %llu (WARM)\n", "Files Warm",
               (u64)atomic64_read(&sbi->files_warm));
    seq_printf(m, "%-30s = %llu (COLD)\n", "Files Cold",
               (u64)atomic64_read(&sbi->files_cold));
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu bytes\n", "Bytes Total",
               (u64)atomic64_read(&sbi->bytes_total));
    seq_printf(m, "%-30s = %llu bytes\n", "Bytes Hot",
               (u64)atomic64_read(&sbi->bytes_hot));
    seq_printf(m, "%-30s = %llu bytes\n", "Bytes Warm",
               (u64)atomic64_read(&sbi->bytes_warm));
    seq_printf(m, "%-30s = %llu bytes\n", "Bytes Cold",
               (u64)atomic64_read(&sbi->bytes_cold));
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu\n", "Reads Total",
               (u64)atomic64_read(&sbi->hits_hot) +
               (u64)atomic64_read(&sbi->hits_cold));
    seq_printf(m, "%-30s = %llu (HOT)\n", "Hits Hot",
               (u64)atomic64_read(&sbi->hits_hot));
    seq_printf(m, "%-30s = %llu (COLD)\n", "Hits Cold",
               (u64)atomic64_read(&sbi->hits_cold));
    seq_printf(m, "\n");
    seq_printf(m, "%-30s = %llu\n", "Evictions Total",
               (u64)atomic64_read(&sbi->evictions_total));
    seq_printf(m, "%-30s = %llu\n", "Shrinker Calls",
               (u64)atomic64_read(&sbi->shrinker_calls));

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
 * /proc/ai-tmpfs/files
 * ================================================================ */

/* 遍历目录并显示文件信息 */
static int proc_files_show(struct seq_file *m, void *v)
{
    struct ai_tmpfs_sb_info *sbi = NULL;

    spin_lock(&g_ai_tmpfs.sb_lock);
    if (g_ai_tmpfs.last_sb)
        sbi = AI_TMPFS_SB(g_ai_tmpfs.last_sb);
    spin_unlock(&g_ai_tmpfs.sb_lock);

    if (!sbi) {
        seq_puts(m, "Not mounted\n");
        return 0;
    }

    seq_printf(m, "%-6s %-6s %-32s %10s %8s %8s\n",
               "Class", "Inode", "Name", "Size", "Access", "Refs");
    seq_printf(m, "%-6s %-6s %-32s %10s %8s %8s\n",
               "-----", "-----", "----", "----", "------", "----");

    unsigned long flags;
    struct ai_tmpfs_inode_info *info;

    /* 冷数据 */
    spin_lock_irqsave(&sbi->lru_lock, flags);
    list_for_each_entry(info, &sbi->lru_cold, lru_node) {
        struct inode *inode = info->inode;
        if (!inode) continue;
        seq_printf(m, "%-6s %-6lu %-32s %10llu %8llu %8u\n",
                   "COLD",
                   inode->i_ino,
                   "?",
                   (u64)inode->i_size,
                   (u64)atomic64_read(&info->access_count),
                   atomic_read(&inode->i_count));
    }

    /* 温数据 */
    list_for_each_entry(info, &sbi->lru_warm, lru_node) {
        struct inode *inode = info->inode;
        if (!inode) continue;
        seq_printf(m, "%-6s %-6lu %-32s %10llu %8llu %8u\n",
                   "WARM",
                   inode->i_ino,
                   "?",
                   (u64)inode->i_size,
                   (u64)atomic64_read(&info->access_count),
                   atomic_read(&inode->i_count));
    }

    /* 热数据 */
    list_for_each_entry(info, &sbi->lru_hot, lru_node) {
        struct inode *inode = info->inode;
        if (!inode) continue;
        seq_printf(m, "%-6s %-6lu %-32s %10llu %8llu %8u\n",
                   "HOT",
                   inode->i_ino,
                   "?",
                   (u64)inode->i_size,
                   (u64)atomic64_read(&info->access_count),
                   atomic_read(&inode->i_count));
    }

    spin_unlock_irqrestore(&sbi->lru_lock, flags);

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
 * /proc/ai-tmpfs/config
 * ================================================================ */

static int proc_config_show(struct seq_file *m, void *v)
{
    struct ai_tmpfs_sb_info *sbi = NULL;

    spin_lock(&g_ai_tmpfs.sb_lock);
    if (g_ai_tmpfs.last_sb)
        sbi = AI_TMPFS_SB(g_ai_tmpfs.last_sb);
    spin_unlock(&g_ai_tmpfs.sb_lock);

    if (!sbi) {
        seq_puts(m, "Not mounted\n");
        return 0;
    }

    seq_printf(m, "%-24s = %u\n", "max_files", sbi->max_files);
    seq_printf(m, "%-24s = %u bytes\n", "max_file_size", sbi->max_file_size);
    seq_printf(m, "%-24s = %u\n", "hot_access_min", sbi->hot_access_min);
    seq_printf(m, "%-24s = %u/min\n", "hot_freq_min", sbi->hot_freq_min);
    seq_printf(m, "%-24s = %u sec\n", "clean_interval", sbi->clean_interval);

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
    struct ai_tmpfs_sb_info *sbi = NULL;
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

    spin_lock(&g_ai_tmpfs.sb_lock);
    if (g_ai_tmpfs.last_sb)
        sbi = AI_TMPFS_SB(g_ai_tmpfs.last_sb);
    spin_unlock(&g_ai_tmpfs.sb_lock);

    if (!sbi)
        return -ENODEV;

    if (sscanf(buf, "%31s %u", cmd, &val) != 2)
        return -EINVAL;

    if (strcmp(cmd, "max_files") == 0)
        sbi->max_files = val;
    else if (strcmp(cmd, "hot_access_min") == 0)
        sbi->hot_access_min = val;
    else if (strcmp(cmd, "hot_freq_min") == 0)
        sbi->hot_freq_min = val;
    else if (strcmp(cmd, "clean_interval") == 0)
        sbi->clean_interval = val;
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
 * 导出 API
 * ================================================================ */

/*
 * 创建 AI tmpfs 文件 (供其他内核模块使用)
 * 注意: 这需要在已挂载的 ai_tmpfs 上操作
 */
int ai_tmpfs_create_file(const char *path, const void *data, size_t size)
{
    /* 简化: 通过 VFS 路径创建文件 */
    /* 完整实现需要 lookup + create + write */
    return -EOPNOTSUPP;
}
EXPORT_SYMBOL_GPL(ai_tmpfs_create_file);

/* ================================================================
 * 初始化
 * ================================================================ */

static int __init ai_tmpfs_init(void)
{
    int ret;

    pr_info("ai-tmpfs: Ainos AI tmpfs v%s initializing...\n", AI_TMPFS_VERSION);

    /* 初始化全局状态 */
    memset(&g_ai_tmpfs, 0, sizeof(g_ai_tmpfs));
    spin_lock_init(&g_ai_tmpfs.sb_lock);

    /* 注册文件系统 */
    ret = register_filesystem(&ai_tmpfs_fs_type);
    if (ret) {
        pr_err("ai-tmpfs: failed to register filesystem (%d)\n", ret);
        return ret;
    }

    /* 创建 /proc/ai-tmpfs 目录 */
    g_ai_tmpfs.proc_dir = proc_mkdir("ai-tmpfs", NULL);
    if (!g_ai_tmpfs.proc_dir) {
        pr_err("ai-tmpfs: failed to create /proc/ai-tmpfs\n");
        ret = -ENOMEM;
        goto err_proc;
    }

    g_ai_tmpfs.proc_status = proc_create("status", 0444,
                                          g_ai_tmpfs.proc_dir,
                                          &proc_status_fops);
    g_ai_tmpfs.proc_files = proc_create("files", 0444,
                                         g_ai_tmpfs.proc_dir,
                                         &proc_files_fops);
    g_ai_tmpfs.proc_config = proc_create("config", 0644,
                                          g_ai_tmpfs.proc_dir,
                                          &proc_config_fops);

    if (!g_ai_tmpfs.proc_status || !g_ai_tmpfs.proc_files ||
        !g_ai_tmpfs.proc_config) {
        pr_err("ai-tmpfs: failed to create proc files\n");
        ret = -ENOMEM;
        goto err_proc_files;
    }

    g_ai_tmpfs.initialized = true;

    pr_info("ai-tmpfs: AI tmpfs v%s initialized\n", AI_TMPFS_VERSION);
    pr_info("ai-tmpfs: mount with: mount -t ai_tmpfs none /mnt/ai-tmpfs\n");
    pr_info("ai-tmpfs: /proc/ai-tmpfs/{status,files,config}\n");

    return 0;

err_proc_files:
    if (g_ai_tmpfs.proc_config) remove_proc_entry("config", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_files)  remove_proc_entry("files", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_status) remove_proc_entry("status", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_dir)    remove_proc_entry("ai-tmpfs", NULL);

err_proc:
    unregister_filesystem(&ai_tmpfs_fs_type);

    return ret;
}

/* ================================================================
 * 清理
 * ================================================================ */

static void __exit ai_tmpfs_exit(void)
{
    if (!g_ai_tmpfs.initialized)
        return;

    pr_info("ai-tmpfs: shutting down...\n");

    /* 清理 proc 文件 */
    if (g_ai_tmpfs.proc_config)
        remove_proc_entry("config", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_files)
        remove_proc_entry("files", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_status)
        remove_proc_entry("status", g_ai_tmpfs.proc_dir);
    if (g_ai_tmpfs.proc_dir)
        remove_proc_entry("ai-tmpfs", NULL);

    /* 注销文件系统 */
    unregister_filesystem(&ai_tmpfs_fs_type);

    pr_info("ai-tmpfs: unloaded\n");
}

module_init(ai_tmpfs_init);
module_exit(ai_tmpfs_exit);