/*
 * AinosOS - fs/tar.h
 * TAR filesystem declarations (for initrd)
 */

#ifndef AINOS_FS_TAR_H
#define AINOS_FS_TAR_H

#include <types.h>

/* TAR header block size */
#define TAR_BLOCK_SIZE      512

/* TAR file types */
#define TAR_TYPE_FILE       '0'
#define TAR_TYPE_HARD_LINK  '1'
#define TAR_TYPE_SYMLINK    '2'
#define TAR_TYPE_CHAR_DEV   '3'
#define TAR_TYPE_BLOCK_DEV  '4'
#define TAR_TYPE_DIR        '5'
#define TAR_TYPE_FIFO       '6'

/* TAR header structure */
struct PACKED tar_header {
    char name[100];
    char mode[8];
    char uid[8];
    char gid[8];
    char size[12];
    char mtime[12];
    char chksum[8];
    char typeflag;
    char linkname[100];
    char magic[6];
    char version[2];
    char uname[32];
    char gname[32];
    char devmajor[8];
    char devminor[8];
    char prefix[155];
    char padding[12];
};

/* TAR filesystem data */
typedef struct {
    uint64_t archive_base;
    uint64_t archive_size;
    int initialized;
} tar_fs_t;

/* TAR entry */
typedef struct {
    char     name[256];
    uint64_t size;
    uint64_t offset;
    uint8_t  type;
} tar_entry_t;

/* TAR functions */
int  tar_init(tar_fs_t *fs, uint64_t archive_base, uint64_t archive_size);
int  tar_get_entry_count(tar_fs_t *fs);
int  tar_find_entry(tar_fs_t *fs, const char *name, tar_entry_t *entry);
int  tar_read_entry(tar_fs_t *fs, tar_entry_t *entry, void *buffer, uint64_t count, uint64_t offset);
int  tar_get_entry_by_index(tar_fs_t *fs, int index, tar_entry_t *entry);
int  tar_parse_header(const struct tar_header *header, tar_entry_t *entry);

/* Convert octal string to integer */
uint64_t tar_octal_to_int(const char *str, size_t len);

/* TAR VFS operations */
int  tar_vfs_mount(void **fs_data, const char *source, uint32_t flags);
int  tar_vfs_unmount(void *fs_data);
int  tar_vfs_open(void *fs_data, vfs_file_t *file, const char *path, int flags);
int  tar_vfs_close(void *fs_data, vfs_file_t *file);
int  tar_vfs_read(void *fs_data, vfs_file_t *file, void *buf, uint64_t count);
int  tar_vfs_write(void *fs_data, vfs_file_t *file, const void *buf, uint64_t count);
int  tar_vfs_seek(void *fs_data, vfs_file_t *file, int64_t offset, int whence);
int  tar_vfs_stat(void *fs_data, vfs_file_t *file, struct vfs_stat *stat);
int  tar_vfs_readdir(void *fs_data, vfs_file_t *file, struct vfs_dirent *dirent, uint32_t index);

#endif /* AINOS_FS_TAR_H */