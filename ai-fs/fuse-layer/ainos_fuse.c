/* fuse-layer/ainos_fuse.c - Ainos AI-FS 内核文件系统实现 */
#define pr_fmt(fmt) "ai-fs: " fmt

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/pagemap.h>
#include <linux/slab.h>
#include <linux/namei.h>
#include <linux/backing-dev.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/mount.h>
#include <linux/inotify.h>
#include <linux/fsnotify.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/list.h>
#include <linux/string.h>
#include <linux/file.h>
#include "ainos_fuse.h"

#define AI_FS_MAGIC 0xA1F555A1
#define AI_FS_PROC_DIR "ainos/ai-fs"

/* 默认低层操作集 */
static struct ai_fs_lowlevel_ops ai_fs_ll_ops;

/* 前向声明 */
static struct inode *ai_fs_iget(struct super_block *sb, unsigned long ino);
static int ai_fs_fill_super(struct super_block *sb, void *data, int silent);
static void ai_fs_kill_sb(struct super_block *sb);
static struct dentry *ai_fs_mount(struct file_system_type *fs_type,
				  int flags, const char *dev_name, void *data);

/* 文件系统类型 */
static struct file_system_type ai_fs_type = {
	.owner		= THIS_MODULE,
	.name		= "ainos-ai-fs",
	.mount		= ai_fs_mount,
	.kill_sb	= ai_fs_kill_sb,
	.fs_flags	= FS_USERNS_MOUNT,
};

/* proc 接口 */
static struct proc_dir_entry *proc_ainos_dir;
static struct proc_dir_entry *proc_ai_fs_dir;

/* 索引相关操作 */
static struct ai_fs_sb_info *sbi;

/* 简单的字符串匹配搜索（模拟） */
static bool match_query(struct ai_fs_index_entry *entry, const char *query)
{
	int i;
	if (!entry->keywords)
		return false;
	for (i = 0; i < entry->num_keywords; i++) {
		if (strstr(entry->keywords[i], query) ||
		    strstr(entry->file_path, query))
			return true;
	}
	return false;
}

/* 索引添加函数 */
static int ai_fs_add_index(const char *path)
{
	struct ai_fs_index_entry *entry;
	char *tmp;
	struct file *f;
	char *kbuf;
	ssize_t len;
	loff_t pos = 0;
	int ret = 0;

	if (!sbi)
		return -ENODEV;

	entry = kmalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return -ENOMEM;

	entry->file_path = kstrdup(path, GFP_KERNEL);
	if (!entry->file_path) {
		kfree(entry);
		return -ENOMEM;
	}

	/* 提取关键词：简单读取文件内容，取前256字节当作关键词 */
	f = filp_open(path, O_RDONLY, 0);
	if (IS_ERR(f)) {
		pr_err("failed to open %s\n", path);
		kfree(entry->file_path);
		kfree(entry);
		return PTR_ERR(f);
	}

	kbuf = kmalloc(PAGE_SIZE, GFP_KERNEL);
	if (!kbuf) {
		filp_close(f, NULL);
		kfree(entry->file_path);
		kfree(entry);
		return -ENOMEM;
	}

	len = kernel_read(f, kbuf, PAGE_SIZE - 1, &pos);
	if (len < 0) {
		pr_err("read error\n");
		kfree(kbuf);
		filp_close(f, NULL);
		kfree(entry->file_path);
		kfree(entry);
		return len;
	}
	kbuf[len] = '\0';

	/* 简单分割成关键词（空格分隔） */
	entry->keywords = NULL;
	entry->num_keywords = 0;
	tmp = kbuf;
	while (*tmp) {
		char *end = strchrnul(tmp, ' ');
		if (end - tmp > 0) {
			size_t kwlen = end - tmp;
			char *kw = kmalloc(kwlen + 1, GFP_KERNEL);
			if (!kw)
				break;
			memcpy(kw, tmp, kwlen);
			kw[kwlen] = '\0';
			/* 重新分配数组 */
			char **new = krealloc(entry->keywords,
					      sizeof(char *) * (entry->num_keywords + 1),
					      GFP_KERNEL);
			if (!new) {
				kfree(kw);
				break;
			}
			entry->keywords = new;
			entry->keywords[entry->num_keywords++] = kw;
		}
		tmp = end;
		if (*tmp)
			tmp++;
	}
	kfree(kbuf);
	filp_close(f, NULL);

	/* inotify 监控 */
	if (sbi->notify_dev) {
		struct path p;
		ret = kern_path(path, LOOKUP_FOLLOW, &p);
		if (ret == 0) {
			entry->watch = inotify_add_watch(sbi->notify_dev, &p,
							IN_MODIFY | IN_DELETE_SELF |
							IN_MOVE_SELF);
			path_put(&p);
			if (IS_ERR(entry->watch)) {
				pr_warn("inotify add failed for %s\n", path);
				entry->watch = NULL;
			}
		}
	} else {
		entry->watch = NULL;
	}

	mutex_lock(&sbi->index_mutex);
	list_add_tail(&entry->list, &sbi->index_list);
	mutex_unlock(&sbi->index_mutex);

	pr_info("indexed %s with %zu keywords\n", path, entry->num_keywords);
	return 0;
}

static void ai_fs_free_index_entry(struct ai_fs_index_entry *entry)
{
	int i;
	if (entry->watch && sbi && sbi->notify_dev) {
		inotify_remove_watch(sbi->notify_dev, entry->watch);
	}
	for (i = 0; i < entry->num_keywords; i++)
		kfree(entry->keywords[i]);
	kfree(entry->keywords);
	kfree(entry->file_path);
	kfree(entry);
}

static int ai_fs_remove_index(const char *path)
{
	struct ai_fs_index_entry *entry, *tmp;
	if (!sbi)
		return -ENODEV;

	mutex_lock(&sbi->index_mutex);
	list_for_each_entry_safe(entry, tmp, &sbi->index_list, list) {
		if (strcmp(entry->file_path, path) == 0) {
			list_del(&entry->list);
			mutex_unlock(&sbi->index_mutex);
			ai_fs_free_index_entry(entry);
			return 0;
		}
	}
	mutex_unlock(&sbi->index_mutex);
	return -ENOENT;
}

/* 提供查询结果列表 */
struct ai_fs_search_ctx {
	char query[256];
	struct list_head results; /* 存放结果 entry 的列表头 */
};

static void ai_fs_search(struct ai_fs_sb_info *sbi, const char *query,
			 struct list_head *results)
{
	struct ai_fs_index_entry *entry;
	INIT_LIST_HEAD(results);
	mutex_lock(&sbi->index_mutex);
	list_for_each_entry(entry, &sbi->index_list, list) {
		if (match_query(entry, query)) {
			list_add_tail(&entry->list, results); /* 借用 list 字段（小心，只是临时） */
		}
	}
	mutex_unlock(&sbi->index_mutex);
}

/* 虚拟 inode 编号分配 */
#define AI_FS_ROOT_INO		1
#define AI_FS_SEARCH_INO	2
#define AI_FS_BY_CONTENT_INO	3
/* 动态查询目录 ino 从 1000 开始，符号链接 ino 基于查询目录 ino 加上索引 */

static struct inode *ai_fs_iget(struct super_block *sb, unsigned long ino)
{
	struct inode *inode;

	inode = new_inode(sb);
	if (!inode)
		return ERR_PTR(-ENOMEM);
	inode->i_ino = ino;
	inode->i_mode = 0;
	inode->i_atime = inode->i_mtime = inode->i_ctime = current_time(inode);
	inode->i_private = NULL;
	return inode;
}

/*
 * 低层操作实现：lookup
 */
static int ai_fs_ll_lookup(struct inode *parent, struct dentry *dentry, unsigned int flags)
{
	struct super_block *sb = dentry->d_sb;
	struct ai_fs_sb_info *info = sb->s_fs_info;
	const char *name = dentry->d_name.name;
	int len = dentry->d_name.len;
	unsigned long ino = 0;
	struct inode *inode = NULL;

	pr_debug("lookup: %.*s in parent %lu\n", len, name, parent->i_ino);

	switch (parent->i_ino) {
	case AI_FS_ROOT_INO:
		if (strncmp(name, "search", len) == 0)
			ino = AI_FS_SEARCH_INO;
		break;
	case AI_FS_SEARCH_INO:
		if (strncmp(name, "by-content", len) == 0)
			ino = AI_FS_BY_CONTENT_INO;
		break;
	case AI_FS_BY_CONTENT_INO:
		/* 每个子目录对应一个查询 */
		ino = AI_FS_QUERY_DIR + (unsigned long) dentry->d_name.hash;
		break;
	default:
		if (parent->i_ino >= AI_FS_QUERY_DIR) {
			/* 在查询目录内查找文件，可能是符号链接 */
			/* 需要查询索引，看 name 是否匹配某个索引条目 */
			struct ai_fs_index_entry *entry;
			mutex_lock(&info->index_mutex);
			list_for_each_entry(entry, &info->index_list, list) {
				/* 用文件名匹配 */
				const char *fname = strrchr(entry->file_path, '/');
				if (!fname)
					fname = entry->file_path;
				else
					fname++;
				if (strncmp(fname, name, len) == 0 && fname[len] == '\0') {
					/* 创建符号链接 inode */
					inode = new_inode(sb);
					if (!inode) {
						mutex_unlock(&info->index_mutex);
						return -ENOMEM;
					}
					inode->i_ino = AI_FS_QUERY_DIR + (unsigned long) entry;
					inode->i_mode = S_IFLNK | 0777;
					inode->i_private = entry; /* 直接存指针 */
					inode->i_op = &ai_fs_symlink_inode_operations;
					inode->i_fop = &simple_symlink_inode_operations; /* 用简单的符号链接操作，但需要自定义 readlink */
					d_add(dentry, inode);
					mutex_unlock(&info->index_mutex);
					return 0;
				}
			}
			mutex_unlock(&info->index_mutex);
			return -ENOENT;
		}
		return -ENOENT;
	}

	if (ino) {
		inode = ai_fs_iget(sb, ino);
		if (IS_ERR(inode))
			return PTR_ERR(inode);
		if (ino == AI_FS_SEARCH_INO || ino == AI_FS_BY_CONTENT_INO) {
			inode->i_mode = S_IFDIR | 0555;
			inode->i_op = &ai_fs_dir_inode_operations;
			inode->i_fop = &ai_fs_dir_file_operations;
		} else if (ino == AI_FS_ROOT_INO) {
			inode->i_mode = S_IFDIR | 0755;
			inode->i_op = &ai_fs_dir_inode_operations;
			inode->i_fop = &ai_fs_dir_file_operations;
		}
		d_add(dentry, inode);
		return 0;
	}
	return -ENOENT;
}

/*
 * readdir 实现
 */
static int ai_fs_ll_readdir(struct file *file, struct dir_context *ctx)
{
	struct inode *inode = file_inode(file);
	struct ai_fs_sb_info *info = inode->i_sb->s_fs_info;

	pr_debug("readdir: ino %lu pos %lld\n", inode->i_ino, ctx->pos);

	switch (inode->i_ino) {
	case AI_FS_ROOT_INO:
		if (!dir_emit(ctx, ".", 1, AI_FS_ROOT_INO, DT_DIR))
			return 0;
		if (!dir_emit(ctx, "..", 2, AI_FS_ROOT_INO, DT_DIR))
			return 0;
		if (ctx->pos == 2) {
			if (!dir_emit(ctx, "search", 6, AI_FS_SEARCH_INO, DT_DIR))
				return 0;
			ctx->pos = 3;
		}
		break;
	case AI_FS_SEARCH_INO:
		if (!dir_emit(ctx, ".", 1, AI_FS_SEARCH_INO, DT_DIR))
			return 0;
		if (!dir_emit(ctx, "..", 2, AI_FS_ROOT_INO, DT_DIR))
			return 0;
		if (ctx->pos == 2) {
			if (!dir_emit(ctx, "by-content", 10, AI_FS_BY_CONTENT_INO, DT_DIR))
				return 0;
			ctx->pos = 3;
		}
		break;
	case AI_FS_BY_CONTENT_INO:
		/* 列出所有曾经查询过的目录？此处简单处理 */
		if (!dir_emit(ctx, ".", 1, AI_FS_BY_CONTENT_INO, DT_DIR))
			return 0;
		if (!dir_emit(ctx, "..", 2, AI_FS_SEARCH_INO, DT_DIR))
			return 0;
		/* 此处可动态生成 */
		break;
	default:
		if (inode->i_ino >= AI_FS_QUERY_DIR) {
			/* 查询目录，列出匹配的文件符号链接 */
			struct ai_fs_index_entry *entry;
			char query[256];
			/* 从 inode 反推查询字符串？这里简单遍历所有索引，但更合理的是将查询存入 inode 的 i_private */
			/* 跳过，留作演示 */
		}
		break;
	}
	return 0;
}

/* 符号链接 readlink 操作 */
static int ai_fs_symlink_readlink(struct dentry *dentry, char __user *buffer, int buflen)
{
	struct inode *inode = d_inode(dentry);
	struct ai_fs_index_entry *entry = inode->i_private;
	if (!entry)
		return -EIO;
	return vfs_readlink(dentry, buffer, buflen, entry->file_path);
}

static const struct inode_operations ai_fs_symlink_inode_operations = {
	.readlink = ai_fs_symlink_readlink,
	.get_link = simple_get_link,
};

/* 目录 inode 操作（无额外） */
static const struct inode_operations ai_fs_dir_inode_operations = {
	.lookup = ai_fs_ll_lookup,
};

static const struct file_operations ai_fs_dir_file_operations = {
	.iterate_shared = ai_fs_ll_readdir,
	.llseek = generic_file_llseek,
};

/* 超级块操作 */
static const struct super_operations ai_fs_sops = {
	.drop_inode = generic_delete_inode,
};

/* 填充超级块 */
static int ai_fs_fill_super(struct super_block *sb, void *data, int silent)
{
	struct ai_fs_sb_info *info;
	struct inode *root_inode;

	info = kzalloc(sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;
	spin_lock_init(&info->lock);
	INIT_LIST_HEAD(&info->index_list);
	mutex_init(&info->index_mutex);
	info->ops = &ai_fs_ll_ops;
	info->userdata = NULL;

	/* inotify 初始化 */
	info->notify_dev = inotify_init(current_user());
	if (IS_ERR(info->notify_dev)) {
		pr_warn("inotify init failed\n");
		info->notify_dev = NULL;
	}

	sb->s_fs_info = info;
	sb->s_magic = AI_FS_MAGIC;
	sb->s_op = &ai_fs_sops;

	root_inode = new_inode(sb);
	if (!root_inode) {
		kfree(info);
		return -ENOMEM;
	}
	root_inode->i_ino = AI_FS_ROOT_INO;
	root_inode->i_mode = S_IFDIR | 0755;
	root_inode->i_op = &ai_fs_dir_inode_operations;
	root_inode->i_fop = &ai_fs_dir_file_operations;
	root_inode->i_atime = root_inode->i_mtime = root_inode->i_ctime = current_time(root_inode);

	sb->s_root = d_make_root(root_inode);
	if (!sb->s_root) {
		kfree(info);
		return -ENOMEM;
	}
	info->root_inode = root_inode;
	sbi = info; /* 全局引用，proc 接口用 */
	return 0;
}

static void ai_fs_kill_sb(struct super_block *sb)
{
	struct ai_fs_sb_info *info = sb->s_fs_info;
	if (info) {
		if (info->notify_dev) {
			/* 移除所有 watch 并销毁 */
			/* 遍历索引列表，移除 watches */
			struct ai_fs_index_entry *entry, *tmp;
			mutex_lock(&info->index_mutex);
			list_for_each_entry_safe(entry, tmp, &info->index_list, list) {
				if (entry->watch)
					inotify_remove_watch(info->notify_dev, entry->watch);
				list_del(&entry->list);
				ai_fs_free_index_entry(entry);
			}
			mutex_unlock(&info->index_mutex);
			/* 关闭 inotify 设备 */
			fput(info->notify_dev->private_file); /* 或者 inotify_release，简单处理 */
		}
		kfree(info);
	}
	sbi = NULL;
	kill_anon_super(sb);
}

static struct dentry *ai_fs_mount(struct file_system_type *fs_type,
				  int flags, const char *dev_name, void *data)
{
	return mount_nodev(fs_type, flags, data, ai_fs_fill_super);
}

/* proc 接口：搜索文件 */
static ssize