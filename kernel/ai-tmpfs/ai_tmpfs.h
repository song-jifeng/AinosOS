#ifndef AINOS_AI_TMPFS_H
#define AINOS_AI_TMPFS_H

#include <linux/types.h>
#include <linux/fs.h>

/* AI tmpfs 接口 */
int ai_tmpfs_create(const char *name, const void *data, size_t size);
int ai_tmpfs_read(const char *name, void **data, size_t *size);
int ai_tmpfs_delete(const char *name);
int ai_tmpfs_list(char *buf, size_t size);
int ai_tmpfs_cleanup(void);

/* 统计 */
struct ai_tmpfs_stats {
    int file_count;
    size_t total_size;
    int hot_files;
    int cold_files;
};

int ai_tmpfs_get_stats(struct ai_tmpfs_stats *stats);

#endif /* AINOS_AI_TMPFS_H */