/*
 * AinosOS - fs/tar.c
 * TAR filesystem implementation for initrd support
 */

#include <types.h>
#include <macros.h>
#include <lib/string.h>
#include <boot/boot.h>
#include <fs/vfs.h>
#include <fs/tar.h>

/*
 * Convert an octal string to an integer
 */
uint64_t tar_octal_to_int(const char *str, size_t len) {
    uint64_t result = 0;
    for (size_t i = 0; i < len && str[i]; i++) {
        if (str[i] >= '0' && str[i] <= '7') {
            result = (result << 3) | (str[i] - '0');
        } else {
            break;
        }
    }
    return result;
}

/*
 * Parse a TAR header into a tar_entry
 */
int tar_parse_header(const struct tar_header *header, tar_entry_t *entry) {
    if (!header || !entry) return -1;

    /* Check magic */
    if (memcmp(header->magic, "ustar", 5) != 0) {
        return -1;  /* Not a TAR file */
    }

    /* Copy name */
    if (header->name[0]) {
        if (header->prefix[0]) {
            snprintf(entry->name, sizeof(entry->name), "%s/%s", header->prefix, header->name);
        } else {
            strncpy(entry->name, header->name, sizeof(entry->name) - 1);
        }
    }

    entry->size = tar_octal_to_int(header->size, sizeof(header->size));
    entry->type = header->typeflag;

    return 0;
}

/*
 * Initialize a TAR filesystem from an archive in memory
 */
int tar_init(tar_fs_t *fs, uint64_t archive_base, uint64_t archive_size) {
    if (!fs) return -1;

    fs->archive_base = archive_base;
    fs->archive_size = archive_size;
    fs->initialized = 1;

    /* Validate - check that the first header is valid */
    struct tar_header *first_header = (struct tar_header*)(uint64_t)archive_base;

    /* Check for empty archive (should have at least one header) */
    if (first_header->name[0] == '\0') {
        boot_printf(BOOT_LOG_WARN "TAR archive appears empty\n");
        return 0;
    }

    /* Count entries */
    int entry_count = 0;
    uint64_t offset = 0;

    while (offset + TAR_BLOCK_SIZE < archive_size) {
        struct tar_header *hdr = (struct tar_header*)(uint64_t)(archive_base + offset);
        if (hdr->name[0] == '\0') break;  /* End of archive */

        tar_entry_t entry;
        if (tar_parse_header(hdr, &entry) == 0) {
            entry_count++;
        }

        /* Move to next entry (header + data, rounded up to block size) */
        uint64_t data_size = tar_octal_to_int(hdr->size, sizeof(hdr->size));
        offset += TAR_BLOCK_SIZE + ((data_size + TAR_BLOCK_SIZE - 1) / TAR_BLOCK_SIZE) * TAR_BLOCK_SIZE;
    }

    boot_printf(BOOT_LOG_OK "TAR archive: %d entries, %llu bytes\n", entry_count, archive_size);
    return 0;
}

/*
 * Get the number of entries in the TAR archive
 */
int tar_get_entry_count(tar_fs_t *fs) {
    if (!fs || !fs->initialized) return 0;

    int count = 0;
    uint64_t offset = 0;

    while (offset + TAR_BLOCK_SIZE < fs->archive_size) {
        struct tar_header *hdr = (struct tar_header*)(uint64_t)(fs->archive_base + offset);
        if (hdr->name[0] == '\0') break;

        tar_entry_t entry;
        if (tar_parse_header(hdr, &entry) == 0) {
            count++;
        }

        uint64_t data_size = tar_octal_to_int(hdr->size, sizeof(hdr->size));
        offset += TAR_BLOCK_SIZE + ((data_size + TAR_BLOCK_SIZE - 1) / TAR_BLOCK_SIZE) * TAR_BLOCK_SIZE;
    }

    return count;
}

/*
 * Get a TAR entry by index
 */
int tar_get_entry_by_index(tar_fs_t *fs, int index, tar_entry_t *entry) {
    if (!fs || !fs->initialized || !entry || index < 0) return -1;

    int count = 0;
    uint64_t offset = 0;

    while (offset + TAR_BLOCK_SIZE < fs->archive_size) {
        struct tar_header *hdr = (struct tar_header*)(uint64_t)(fs->archive_base + offset);
        if (hdr->name[0] == '\0') break;

        if (count == index) {
            if (tar_parse_header(hdr, entry) == 0) {
                entry->offset = offset + TAR_BLOCK_SIZE;
                return 0;
            }
            return -1;
        }

        uint64_t data_size = tar_octal_to_int(hdr->size, sizeof(hdr->size));
        offset += TAR_BLOCK_SIZE + ((data_size + TAR_BLOCK_SIZE - 1) / TAR_BLOCK_SIZE) * TAR_BLOCK_SIZE;
        count++;
    }

    return -1;
}

/*
 * Find a TAR entry by name
 */
int tar_find_entry(tar_fs_t *fs, const char *name, tar_entry_t *entry) {
    if (!fs || !fs->initialized || !name || !entry) return -1;

    uint64_t offset = 0;

    /* Strip leading slash if present */
    if (name[0] == '/') name++;

    while (offset + TAR_BLOCK_SIZE < fs->archive_size) {
        struct tar_header *hdr = (struct tar_header*)(uint64_t)(fs->archive_base + offset);
        if (hdr->name[0] == '\0') break;

        if (tar_parse_header(hdr, entry) == 0) {
            /* Compare entry name */
            const char *entry_name = entry->name;
            if (entry_name[0] == '/') entry_name++;

            if (strcmp(entry_name, name) == 0) {
                entry->offset = offset + TAR_BLOCK_SIZE;
                return 0;
            }
        }

        uint64_t data_size = tar_octal_to_int(hdr->size, sizeof(hdr->size));
        offset += TAR_BLOCK_SIZE + ((data_size + TAR_BLOCK_SIZE - 1) / TAR_BLOCK_SIZE) * TAR_BLOCK_SIZE;
    }

    return -1;
}

/*
 * Read data from a TAR entry
 */
int tar_read_entry(tar_fs_t *fs, tar_entry_t *entry, void *buffer, uint64_t count, uint64_t offset_in_entry) {
    if (!fs || !fs->initialized || !entry || !buffer) return -1;

    if (offset_in_entry >= entry->size) return 0;

    uint64_t to_read = entry->size - offset_in_entry;
    if (count < to_read) to_read = count;

    uint64_t src = fs->archive_base + entry->offset + offset_in_entry;
    memcpy(buffer, (void*)(uint64_t)src, to_read);

    return to_read;
}

/* ================================================================ */
/* TAR VFS operations                                               */
/* ================================================================ */

/*
 * TAR private file data
 */
typedef struct {
    tar_entry_t entry;
    uint64_t    offset;
    int         is_dir;
    int         entry_count;
    int         current_index;
} tar_file_private_t;

/*
 * Mount a TAR filesystem
 */
int tar_vfs_mount(void **fs_data, const char *source, uint32_t flags) {
    tar_fs_t *fs = (tar_fs_t*)boot_alloc(sizeof(tar_fs_t));
    if (!fs) return -1;

    /* Parse source: "initrd@base,size" */
    uint64_t base = 0, size = 0;
    if (sscanf(source, "initrd@%llu,%llu", &base, &size) >= 2) {
        tar_init(fs, base, size);
    } else {
        boot_printf(BOOT_LOG_WARN "TAR: Invalid source format: %s\n", source);
        boot_free(fs);
        return -1;
    }

    *fs_data = fs;
    return 0;
}

/*
 * Unmount TAR filesystem
 */
int tar_vfs_unmount(void *fs_data) {
    if (fs_data) {
        boot_free(fs_data);
    }
    return 0;
}

/*
 * Open a file in the TAR archive
 */
int tar_vfs_open(void *fs_data, vfs_file_t *file, const char *path, int flags) {
    tar_fs_t *fs = (tar_fs_t*)fs_data;
    if (!fs || !file || !path) return -1;

    /* Strip leading slash */
    const char *name = path;
    if (name[0] == '/') name++;

    tar_file_private_t *priv = (tar_file_private_t*)boot_alloc(sizeof(tar_file_private_t));
    if (!priv) return -1;

    /* Check if it's the root directory */
    if (name[0] == '\0' || strcmp(name, ".") == 0) {
        priv->is_dir = 1;
        priv->entry_count = tar_get_entry_count(fs);
        priv->current_index = 0;
        file->private_data = priv;
        return 0;
    }

    /* Find the entry */
    if (tar_find_entry(fs, name, &priv->entry) != 0) {
        boot_free(priv);
        return -1;
    }

    priv->offset = 0;
    priv->is_dir = (priv->entry.type == TAR_TYPE_DIR);
    file->private_data = priv;
    file->pos = 0;

    return 0;
}

/*
 * Close a TAR file
 */
int tar_vfs_close(void *fs_data, vfs_file_t *file) {
    if (file && file->private_data) {
        boot_free(file->private_data);
        file->private_data = NULL;
    }
    return 0;
}

/*
 * Read from a TAR file
 */
int tar_vfs_read(void *fs_data, vfs_file_t *file, void *buf, uint64_t count) {
    tar_fs_t *fs = (tar_fs_t*)fs_data;
    tar_file_private_t *priv = (tar_file_private_t*)file->private_data;

    if (!fs || !priv || priv->is_dir) return -1;

    int bytes = tar_read_entry(fs, &priv->entry, buf, count, priv->offset);
    if (bytes > 0) {
        priv->offset += bytes;
        file->pos += bytes;
    }

    return bytes;
}

/*
 * Write to a TAR file (read-only, always fails)
 */
int tar_vfs_write(void *fs_data, vfs_file_t *file, const void *buf, uint64_t count) {
    return -1;  /* Read-only filesystem */
}

/*
 * Seek within a TAR file
 */
int tar_vfs_seek(void *fs_data, vfs_file_t *file, int64_t offset, int whence) {
    tar_file_private_t *priv = (tar_file_private_t*)file->private_data;
    if (!priv || priv->is_dir) return -1;

    uint64_t new_offset;
    switch (whence) {
        case VFS_SEEK_SET:
            new_offset = offset;
            break;
        case VFS_SEEK_CUR:
            new_offset = priv->offset + offset;
            break;
        case VFS_SEEK_END:
            new_offset = priv->entry.size + offset;
            break;
        default:
            return -1;
    }

    if (new_offset > priv->entry.size) new_offset = priv->entry.size;
    priv->offset = new_offset;
    file->pos = new_offset;
    return 0;
}

/*
 * Stat a TAR file
 */
int tar_vfs_stat(void *fs_data, vfs_file_t *file, struct vfs_stat *stat) {
    tar_file_private_t *priv = (tar_file_private_t*)file->private_data;
    if (!priv || !stat) return -1;

    if (priv->is_dir) {
        stat->type = VFS_DIRECTORY;
        stat->size = 0;
    } else {
        stat->type = VFS_FILE;
        stat->size = priv->entry.size;
    }
    stat->mode = 0444;
    stat->uid = 0;
    stat->gid = 0;

    return 0;
}

/*
 * Read a directory entry from the TAR archive
 */
int tar_vfs_readdir(void *fs_data, vfs_file_t *file, struct vfs_dirent *dirent, uint32_t index) {
    tar_fs_t *fs = (tar_fs_t*)fs_data;
    if (!fs || !dirent) return -1;

    tar_entry_t entry;
    if (tar_get_entry_by_index(fs, index, &entry) != 0) {
        return -1;
    }

    /* Extract just the filename from the path */
    const char *name = entry.name;
    const char *slash = strrchr(name, '/');
    if (slash) {
        name = slash + 1;
    }

    strncpy(dirent->name, name, VFS_MAX_NAME - 1);
    dirent->size = entry.size;
    dirent->type = (entry.type == TAR_TYPE_DIR) ? VFS_DIRECTORY : VFS_FILE;
    dirent->inode = index;

    return 0;
}

/*
 * Register the TAR filesystem with VFS
 */
void tar_register(void) {
    static vfs_ops_t tar_ops = {
        .mount   = tar_vfs_mount,
        .unmount = tar_vfs_unmount,
        .open    = tar_vfs_open,
        .close   = tar_vfs_close,
        .read    = tar_vfs_read,
        .write   = tar_vfs_write,
        .seek    = tar_vfs_seek,
        .stat    = tar_vfs_stat,
        .readdir = tar_vfs_readdir,
        .mkdir   = NULL,
    };

    vfs_register_fs(VFS_FS_TAR, &tar_ops);
    boot_printf(BOOT_LOG_OK "TAR filesystem registered\n");
}