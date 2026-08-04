/*
 * AinosOS - fs/vfs.h
 * Virtual File System declarations
 */

#ifndef AINOS_FS_VFS_H
#define AINOS_FS_VFS_H

#include <types.h>

/* Maximum path length */
#define VFS_MAX_PATH        4096
#define VFS_MAX_NAME        256
#define VFS_MAX_FILESYSTEMS 16
#define VFS_MAX_OPEN_FILES  64

/* File type flags */
#define VFS_FILE            0x01
#define VFS_DIRECTORY       0x02
#define VFS_CHAR_DEVICE     0x03
#define VFS_BLOCK_DEVICE    0x04
#define VFS_SYMLINK         0x05
#define VFS_MOUNTPOINT      0x08

/* File open flags */
#define VFS_O_RDONLY        0x0001
#define VFS_O_WRONLY        0x0002
#define VFS_O_RDWR          0x0004
#define VFS_O_CREAT         0x0008
#define VFS_O_TRUNC         0x0010
#define VFS_O_APPEND        0x0020
#define VFS_O_EXCL          0x0040

/* Seek modes */
#define VFS_SEEK_SET        0
#define VFS_SEEK_CUR        1
#define VFS_SEEK_END        2

/* Stat structure */
struct vfs_stat {
    uint32_t type;
    uint64_t size;
    uint32_t mode;
    uint32_t uid;
    uint32_t gid;
    uint64_t atime;
    uint64_t mtime;
    uint64_t ctime;
};

/* Directory entry */
struct vfs_dirent {
    char     name[VFS_MAX_NAME];
    uint32_t type;
    uint64_t size;
    uint32_t inode;
};

/* File descriptor */
typedef struct {
    int      used;
    int      flags;
    uint64_t pos;
    uint32_t mount_id;
    uint32_t inode;
    void    *private_data;
} vfs_file_t;

/* Filesystem operations */
typedef struct vfs_ops {
    int   (*mount)(void **fs_data, const char *source, uint32_t flags);
    int   (*unmount)(void *fs_data);
    int   (*open)(void *fs_data, vfs_file_t *file, const char *path, int flags);
    int   (*close)(void *fs_data, vfs_file_t *file);
    int   (*read)(void *fs_data, vfs_file_t *file, void *buf, uint64_t count);
    int   (*write)(void *fs_data, vfs_file_t *file, const void *buf, uint64_t count);
    int   (*seek)(void *fs_data, vfs_file_t *file, int64_t offset, int whence);
    int   (*stat)(void *fs_data, vfs_file_t *file, struct vfs_stat *stat);
    int   (*readdir)(void *fs_data, vfs_file_t *file, struct vfs_dirent *dirent, uint32_t index);
    int   (*mkdir)(void *fs_data, const char *path, uint32_t mode);
} vfs_ops_t;

/* Mounted filesystem */
typedef struct {
    int      used;
    char     mount_point[VFS_MAX_PATH];
    int      fs_type;
    void    *fs_data;
    vfs_ops_t *ops;
} vfs_mount_t;

/* VFS functions */
int  vfs_init(void);
int  vfs_mount(const char *path, const char *source, int fs_type, uint32_t flags);
int  vfs_unmount(const char *path);
int  vfs_open(const char *path, int flags);
int  vfs_close(int fd);
int  vfs_read(int fd, void *buf, uint64_t count);
int  vfs_write(int fd, const void *buf, uint64_t count);
int  vfs_seek(int fd, int64_t offset, int whence);
int  vfs_stat(int fd, struct vfs_stat *stat);
int  vfs_readdir(int fd, struct vfs_dirent *dirent, uint32_t index);
int  vfs_fstat(const char *path, struct vfs_stat *stat);
int  vfs_mkdir(const char *path, uint32_t mode);

/* Path resolution */
int  vfs_resolve_path(const char *path, char *resolved, uint32_t *mount_id);
int  vfs_mount_root(const char *source, int fs_type);

/* Root filesystem */
#define VFS_FS_TAR      0
#define VFS_FS_DEVFS    1
#define VFS_FS_TMPFS    2

/* Global VFS state */
extern vfs_mount_t g_vfs_mounts[VFS_MAX_FILESYSTEMS];
extern vfs_file_t g_vfs_files[VFS_MAX_OPEN_FILES];

#endif /* AINOS_FS_VFS_H */