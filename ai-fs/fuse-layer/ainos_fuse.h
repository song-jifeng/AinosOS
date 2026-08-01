/* fuse-layer/ainos_fuse.h - Ainos AI-FS 内核头文件 */
#ifndef _AINOS_FUSE_H
#define _AINOS_FUSE_H

#include <linux/fs.h>
#include <linux/types.h>
#include <linux/inotify.h>
#include <linux/spinlock.h>

/* 低层操作，仿照 libfuse 的 fuse_lowlevel_ops */
struct ai_fs_lowlevel_ops {
	void (*init)(void *userdata);
	void (*destroy)(void *userdata);
	int (*lookup)(struct inode *parent, struct dentry *dentry, unsigned int flags);
	int (*getattr)(struct inode *inode, struct kstat *stat);
	int (*readlink)(struct inode *inode, char __user *buffer, int buflen);
	int (*open)(struct inode *inode, struct file *file);
	int (*read)(struct file *file, char __user *buf, size_t size, loff_t *offset);
	int (*readdir)(struct file *file, struct dir_context *ctx);
	int (*release)(struct inode *inode, struct file *file);
};

/* AI-FS 超级块私有数据 */
struct ai_fs_sb_info {
	spinlock_t lock;
	struct inode *root_inode;
	const struct ai_fs_lowlevel_ops *ops;
	void *userdata;
	struct list_head index_list;	/* 索引条目列表 */
	struct inotify_device *notify_dev;	/* inotify 设备 */
	struct mutex index_mutex;
};

/* 索引条目 */
struct ai_fs_index_entry {
	struct list_head list;
	char *file_path;		/* 真实文件绝对路径 */
	char **keywords;		/* 提取的关键词 */
	size_t num_keywords;
	struct inotify_watch *watch;	/* inotify 监控句柄 */
};

/* 虚拟目录结构定义 */
#define AI_FS_ROOT		1
#define AI_FS_SEARCH		2
#define AI_FS_SEARCH_BY_CONTENT	3
#define AI_FS_QUERY_DIR		4
#define AI_FS_SYMLINK		5

/* inotify 接口 */
struct inotify_device *ai_fs_inotify_init(void);
int ai_fs_inotify_add_watch(struct inotify_device *dev,
			    const char *path, u32 mask);
void ai_fs_inotify_remove_watch(struct inotify_device *dev,
				struct inotify_watch *watch);

#endif /* _AINOS_FUSE_H */