/*
 * AinosOS - fs/vfs.c
 * Virtual File System implementation
 */

#include <types.h>
#include <macros.h>
#include <lib/string.h>
#include <boot/boot.h>
#include <fs/vfs.h>

/* Global VFS state */
vfs_mount_t g_vfs_mounts[VFS_MAX_FILESYSTEMS];
vfs_file_t g_vfs_files[VFS_MAX_OPEN_FILES];

/* Registered filesystem drivers */
static vfs_ops_t *g_fs_drivers[VFS_MAX_FILESYSTEMS];
static int g_fs_driver_count = 0;

/*
 * Initialize the VFS layer
 */
int vfs_init(void) {
    boot_printf(BOOT_LOG_INIT "Initializing VFS...\n");

    /* Clear all file structures */
    for (int i = 0; i < VFS_MAX_OPEN_FILES; i++) {
        g_vfs_files[i].used = 0;
    }

    /* Clear all mount structures */
    for (int i = 0; i < VFS_MAX_FILESYSTEMS; i++) {
        g_vfs_mounts[i].used = 0;
    }

    /* Clear filesystem drivers */
    for (int i = 0; i < VFS_MAX_FILESYSTEMS; i++) {
        g_fs_drivers[i] = NULL;
    }
    g_fs_driver_count = 0;

    boot_printf(BOOT_LOG_OK "VFS initialized\n");
    return 0;
}

/*
 * Register a filesystem driver
 */
int vfs_register_fs(int fs_type, vfs_ops_t *ops) {
    if (fs_type < 0 || fs_type >= VFS_MAX_FILESYSTEMS) return -1;
    if (g_fs_driver_count >= VFS_MAX_FILESYSTEMS) return -1;

    g_fs_drivers[fs_type] = ops;
    g_fs_driver_count++;
    return 0;
}

/*
 * Mount a filesystem at a path
 */
int vfs_mount(const char *path, const char *source, int fs_type, uint32_t flags) {
    if (!path || !source) return -1;

    /* Find a free mount slot */
    int mount_id = -1;
    for (int i = 0; i < VFS_MAX_FILESYSTEMS; i++) {
        if (!g_vfs_mounts[i].used) {
            mount_id = i;
            break;
        }
    }

    if (mount_id < 0) return -1;  /* No free mount slots */

    /* Check if filesystem driver is registered */
    if (fs_type < 0 || fs_type >= VFS_MAX_FILESYSTEMS || !g_fs_drivers[fs_type]) {
        return -1;
    }

    vfs_mount_t *mount = &g_vfs_mounts[mount_id];
    mount->fs_type = fs_type;
    mount->ops = g_fs_drivers[fs_type];
    strncpy(mount->mount_point, path, VFS_MAX_PATH - 1);

    /* Call the filesystem's mount function */
    if (mount->ops->mount) {
        if (mount->ops->mount(&mount->fs_data, source, flags) != 0) {
            mount->used = 0;
            return -1;
        }
    }

    mount->used = 1;
    boot_printf("  Mounted %s at %s\n", source, path);
    return 0;
}

/*
 * Unmount a filesystem
 */
int vfs_unmount(const char *path) {
    for (int i = 0; i < VFS_MAX_FILESYSTEMS; i++) {
        if (g_vfs_mounts[i].used && strcmp(g_vfs_mounts[i].mount_point, path) == 0) {
            if (g_vfs_mounts[i].ops->unmount) {
                g_vfs_mounts[i].ops->unmount(g_vfs_mounts[i].fs_data);
            }
            g_vfs_mounts[i].used = 0;
            return 0;
        }
    }
    return -1;
}

/*
 * Resolve a path to a mount point and relative path
 */
int vfs_resolve_path(const char *path, char *resolved, uint32_t *mount_id) {
    if (!path || !resolved || !mount_id) return -1;

    /* Find the deepest matching mount point */
    int best_match = -1;
    size_t best_len = 0;

    for (int i = 0; i < VFS_MAX_FILESYSTEMS; i++) {
        if (g_vfs_mounts[i].used) {
            size_t mlen = strlen(g_vfs_mounts[i].mount_point);
            if (strncmp(path, g_vfs_mounts[i].mount_point, mlen) == 0) {
                if (mlen > best_len) {
                    best_match = i;
                    best_len = mlen;
                }
            }
        }
    }

    if (best_match < 0) return -1;

    *mount_id = best_match;

    /* Return the relative path within the mount */
    const char *rel = path + best_len;
    if (*rel == '\0' || *rel == '/') {
        strcpy(resolved, rel);
        if (resolved[0] == '\0') {
            strcpy(resolved, "/");
        }
    } else {
        strcpy(resolved, rel);
    }

    return 0;
}

/*
 * Open a file
 */
int vfs_open(const char *path, int flags) {
    if (!path) return -1;

    /* Find a free file descriptor */
    int fd = -1;
    for (int i = 0; i < VFS_MAX_OPEN_FILES; i++) {
        if (!g_vfs_files[i].used) {
            fd = i;
            break;
        }
    }

    if (fd < 0) return -1;  /* Too many open files */

    /* Resolve the path */
    char resolved_path[VFS_MAX_PATH];
    uint32_t mount_id;

    if (vfs_resolve_path(path, resolved_path, &mount_id) != 0) {
        return -1;
    }

    vfs_mount_t *mount = &g_vfs_mounts[mount_id];
    vfs_file_t *file = &g_vfs_files[fd];

    file->used = 1;
    file->flags = flags;
    file->pos = 0;
    file->mount_id = mount_id;
    file->private_data = NULL;

    /* Call the filesystem's open function */
    if (mount->ops->open) {
        if (mount->ops->open(mount->fs_data, file, resolved_path, flags) != 0) {
            file->used = 0;
            return -1;
        }
    }

    return fd;
}

/*
 * Close a file
 */
int vfs_close(int fd) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->close) {
        mount->ops->close(mount->fs_data, file);
    }

    file->used = 0;
    return 0;
}

/*
 * Read from a file
 */
int vfs_read(int fd, void *buf, uint64_t count) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->read) {
        return mount->ops->read(mount->fs_data, file, buf, count);
    }

    return -1;
}

/*
 * Write to a file
 */
int vfs_write(int fd, const void *buf, uint64_t count) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->write) {
        return mount->ops->write(mount->fs_data, file, buf, count);
    }

    return -1;
}

/*
 * Seek within a file
 */
int vfs_seek(int fd, int64_t offset, int whence) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->seek) {
        return mount->ops->seek(mount->fs_data, file, offset, whence);
    }

    return -1;
}

/*
 * Get file status
 */
int vfs_stat(int fd, struct vfs_stat *stat) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->stat) {
        return mount->ops->stat(mount->fs_data, file, stat);
    }

    return -1;
}

/*
 * Read a directory entry
 */
int vfs_readdir(int fd, struct vfs_dirent *dirent, uint32_t index) {
    if (fd < 0 || fd >= VFS_MAX_OPEN_FILES || !g_vfs_files[fd].used) {
        return -1;
    }

    vfs_file_t *file = &g_vfs_files[fd];
    vfs_mount_t *mount = &g_vfs_mounts[file->mount_id];

    if (mount->ops->readdir) {
        return mount->ops->readdir(mount->fs_data, file, dirent, index);
    }

    return -1;
}

/*
 * Get file status by path
 */
int vfs_fstat(const char *path, struct vfs_stat *stat) {
    int fd = vfs_open(path, VFS_O_RDONLY);
    if (fd < 0) return -1;

    int ret = vfs_stat(fd, stat);
    vfs_close(fd);
    return ret;
}

/*
 * Create a directory
 */
int vfs_mkdir(const char *path, uint32_t mode) {
    char resolved_path[VFS_MAX_PATH];
    uint32_t mount_id;

    if (vfs_resolve_path(path, resolved_path, &mount_id) != 0) {
        return -1;
    }

    vfs_mount_t *mount = &g_vfs_mounts[mount_id];

    if (mount->ops->mkdir) {
        return mount->ops->mkdir(mount->fs_data, resolved_path, mode);
    }

    return -1;
}

/*
 * Mount the root filesystem
 */
int vfs_mount_root(const char *source, int fs_type) {
    return vfs_mount("/", source, fs_type, 0);
}