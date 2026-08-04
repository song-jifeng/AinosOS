/*
 * AinosOS - boot/multiboot.h
 * Multiboot and Multiboot2 header definitions
 */

#ifndef AINOS_BOOT_MULTIBOOT_H
#define AINOS_BOOT_MULTIBOOT_H

#include <types.h>

/* Multiboot2 magic number */
#define MULTIBOOT2_MAGIC            0x36D76289
#define MULTIBOOT2_BOOTLOADER_MAGIC 0x36D76289

/* Multiboot (v1) magic */
#define MULTIBOOT_MAGIC             0x1BADB002
#define MULTIBOOT_BOOTLOADER_MAGIC  0x2BADB002

/* Multiboot2 header flags */
#define MULTIBOOT2_HEADER_TAG_INFORMATION_REQUEST  1
#define MULTIBOOT2_HEADER_TAG_ADDRESS              2
#define MULTIBOOT2_HEADER_TAG_ENTRY_ADDRESS        3
#define MULTIBOOT2_HEADER_TAG_CONSOLE_FLAGS        4
#define MULTIBOOT2_HEADER_TAG_FRAMEBUFFER          5
#define MULTIBOOT2_HEADER_TAG_MODULE_ALIGN         6
#define MULTIBOOT2_HEADER_TAG_EFI_BS               7
#define MULTIBOOT2_HEADER_TAG_ENTRY_ADDRESS_EFI64  9
#define MULTIBOOT2_HEADER_TAG_RELOCATABLE          10

/* Multiboot2 header tag structure */
struct PACKED multiboot2_header_tag {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
};

/* Multiboot2 information request tag */
struct PACKED multiboot2_header_tag_info_req {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint32_t requests[];
};

/* Multiboot2 header address tag */
struct PACKED multiboot2_header_tag_address {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint32_t header_addr;
    uint32_t load_addr;
    uint32_t load_end_addr;
    uint32_t bss_end_addr;
};

/* Multiboot2 entry address tag */
struct PACKED multiboot2_header_tag_entry {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint32_t entry_addr;
};

/* Multiboot2 framebuffer tag */
struct PACKED multiboot2_header_tag_framebuffer {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint32_t width;
    uint32_t height;
    uint32_t depth;
};

/* Multiboot2 EFI64 entry point */
struct PACKED multiboot2_header_tag_entry_efi64 {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint64_t entry_addr;
};

/* Multiboot2 relocatable header */
struct PACKED multiboot2_header_tag_relocatable {
    uint16_t type;
    uint16_t flags;
    uint32_t size;
    uint32_t min_addr;
    uint32_t max_addr;
    uint32_t align;
    uint32_t preference;
};

/* ------------------------------------------------------------------ */
/* Multiboot2 information structure (passed by bootloader)             */
/* ------------------------------------------------------------------ */

/* Basic info request tag types */
#define MULTIBOOT2_TAG_BASIC_MEMINFO         1
#define MULTIBOOT2_TAG_BOOT_DEVICE           2
#define MULTIBOOT2_TAG_CMD_LINE              3
#define MULTIBOOT2_TAG_MODULE                4
#define MULTIBOOT2_TAG_ELF_SYMS              6
#define MULTIBOOT2_TAG_MEMORY_MAP            8
#define MULTIBOOT2_TAG_FRAMEBUFFER_INFO      8   /* Actually tag 8 is also used for something else */
#define MULTIBOOT2_TAG_FRAMEBUFFER           8
#define MULTIBOOT2_TAG_APM_TABLE             10
#define MULTIBOOT2_TAG_VBE_INFO              11
#define MULTIBOOT2_TAG_ACPI_RSDP_V1          14
#define MULTIBOOT2_TAG_ACPI_RSDP_V2          15
#define MULTIBOOT2_TAG_NETWORK_INFO          16
#define MULTIBOOT2_TAG_EFI_MEMORY_MAP        17
#define MULTIBOOT2_TAG_EFI_BS                18
#define MULTIBOOT2_TAG_EFI_IMAGE_32          19
#define MULTIBOOT2_TAG_EFI_IMAGE_64          20
#define MULTIBOOT2_TAG_LOAD_BASE_ADDR        21
#define MULTIBOOT2_TAG_EFI_SDT_32            22
#define MULTIBOOT2_TAG_EFI_SDT_64            23

/* Multiboot2 info structure start */
struct PACKED multiboot2_info {
    uint32_t total_size;
    uint32_t reserved;
};

/* Generic tag header */
struct PACKED multiboot2_tag {
    uint32_t type;
    uint32_t size;
};

/* Basic memory info */
struct PACKED multiboot2_tag_basic_meminfo {
    uint32_t type;
    uint32_t size;
    uint32_t mem_lower;
    uint32_t mem_upper;
};

/* Boot device */
struct PACKED multiboot2_tag_bootdev {
    uint32_t type;
    uint32_t size;
    uint32_t biosdev;
    uint32_t partition;
    uint32_t sub_partition;
};

/* Command line */
struct PACKED multiboot2_tag_cmdline {
    uint32_t type;
    uint32_t size;
    char     cmdline[];
};

/* Module */
struct PACKED multiboot2_tag_module {
    uint32_t type;
    uint32_t size;
    uint32_t mod_start;
    uint32_t mod_end;
    char     cmdline[];
};

/* Memory map entry */
struct PACKED multiboot2_mmap_entry {
    uint64_t addr;
    uint64_t len;
    uint32_t type;
    uint32_t zero;
};

/* Memory map type values */
#define MULTIBOOT2_MEMORY_AVAILABLE         1
#define MULTIBOOT2_MEMORY_RESERVED          2
#define MULTIBOOT2_MEMORY_ACPI_RECLAIMABLE  3
#define MULTIBOOT2_MEMORY_NVS               4
#define MULTIBOOT2_MEMORY_BADRAM            5

/* Memory map tag */
struct PACKED multiboot2_tag_mmap {
    uint32_t type;
    uint32_t size;
    uint32_t entry_size;
    uint32_t entry_version;
    struct multiboot2_mmap_entry entries[];
};

/* Framebuffer info */
struct PACKED multiboot2_tag_framebuffer {
    uint32_t type;
    uint32_t size;
    uint64_t framebuffer_addr;
    uint32_t framebuffer_pitch;
    uint32_t framebuffer_width;
    uint32_t framebuffer_height;
    uint8_t  framebuffer_bpp;
    uint8_t  framebuffer_type;
    uint16_t reserved;
    union {
        struct {
            uint32_t framebuffer_palette_addr;
            uint16_t framebuffer_palette_num_colors;
        };
        struct {
            uint8_t  framebuffer_red_field_position;
            uint8_t  framebuffer_red_mask_size;
            uint8_t  framebuffer_green_field_position;
            uint8_t  framebuffer_green_mask_size;
            uint8_t  framebuffer_blue_field_position;
            uint8_t  framebuffer_blue_mask_size;
        };
    };
};

/* Framebuffer types */
#define MULTIBOOT2_FRAMEBUFFER_TYPE_INDEXED     0
#define MULTIBOOT2_FRAMEBUFFER_TYPE_RGB         1
#define MULTIBOOT2_FRAMEBUFFER_TYPE_EGA_TEXT    2

/* ACPI RSDP (v1) */
struct PACKED multiboot2_tag_acpi_rsdp_v1 {
    uint32_t type;
    uint32_t size;
    uint8_t  rsdp[20]; /* ACPI 1.0 RSDP */
};

/* ACPI RSDP (v2) */
struct PACKED multiboot2_tag_acpi_rsdp_v2 {
    uint32_t type;
    uint32_t size;
    uint8_t  rsdp[36]; /* ACPI 2.0+ RSDP */
};

/* ELF symbols */
struct PACKED multiboot2_tag_elf_syms {
    uint32_t type;
    uint32_t size;
    uint32_t num;
    uint32_t entsize;
    uint32_t shndx;
    char     sections[];
};

/* EFI memory map */
struct PACKED multiboot2_tag_efi_mmap {
    uint32_t type;
    uint32_t size;
    uint32_t desc_size;
    uint32_t desc_version;
    uint8_t  efi_mmap[];
};

/* ------------------------------------------------------------------ */
/* Multiboot (v1) header                                              */
/* ------------------------------------------------------------------ */

/* Multiboot v1 flags */
#define MULTIBOOT_FLAG_PAGE_ALIGN    (1 << 0)
#define MULTIBOOT_FLAG_MEMORY_INFO   (1 << 1)
#define MULTIBOOT_FLAG_VIDEO_MODE    (1 << 2)
#define MULTIBOOT_FLAG_AOUT_KLUDGE   (1 << 16)

/* Multiboot v1 header */
struct PACKED multiboot_header {
    uint32_t magic;
    uint32_t flags;
    uint32_t checksum;
    uint32_t header_addr;
    uint32_t load_addr;
    uint32_t load_end_addr;
    uint32_t bss_end_addr;
    uint32_t entry_addr;
    uint32_t mode_type;
    uint32_t width;
    uint32_t height;
    uint32_t depth;
};

/* Multiboot v1 info structure */
struct PACKED multiboot_info {
    uint32_t flags;
    uint32_t mem_lower;
    uint32_t mem_upper;
    uint32_t boot_device;
    uint32_t cmdline;
    uint32_t mods_count;
    uint32_t mods_addr;
    uint32_t syms[4];
    uint32_t mmap_length;
    uint32_t mmap_addr;
    uint32_t drives_length;
    uint32_t drives_addr;
    uint32_t config_table;
    uint32_t boot_loader_name;
    uint32_t apm_table;
    uint32_t vbe_control_info;
    uint32_t vbe_mode_info;
    uint32_t vbe_mode;
    uint32_t vbe_interface_seg;
    uint32_t vbe_interface_off;
    uint32_t vbe_interface_len;
    uint64_t framebuffer_addr;
    uint32_t framebuffer_pitch;
    uint32_t framebuffer_width;
    uint32_t framebuffer_height;
    uint8_t  framebuffer_bpp;
    uint8_t  framebuffer_type;
    uint8_t  framebuffer_red_field_position;
    uint8_t  framebuffer_red_mask_size;
    uint8_t  framebuffer_green_field_position;
    uint8_t  framebuffer_green_mask_size;
    uint8_t  framebuffer_blue_field_position;
    uint8_t  framebuffer_blue_mask_size;
};

#endif /* AINOS_BOOT_MULTIBOOT_H */