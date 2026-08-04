/*
 * AinosOS - boot/boot.h
 * Boot header definitions and early boot interface
 */

#ifndef AINOS_BOOT_BOOT_H
#define AINOS_BOOT_BOOT_H

#include <types.h>
#include "multiboot.h"

/* Boot-time information passed from early assembly to C code */
struct PACKED boot_info {
    uint64_t magic;                      /* Multiboot magic */
    uint64_t mb_info_addr;               /* Multiboot info struct address */
    uint64_t kernel_base;                /* Physical base address of kernel */
    uint64_t kernel_end;                 /* Physical end address of kernel */
    uint64_t initrd_base;                /* Physical base of initrd */
    uint64_t initrd_end;                 /* Physical end of initrd */
    uint64_t framebuffer_addr;           /* Framebuffer physical address */
    uint64_t framebuffer_width;          /* Framebuffer width in pixels */
    uint64_t framebuffer_height;         /* Framebuffer height in pixels */
    uint64_t framebuffer_pitch;          /* Framebuffer pitch (bytes per line) */
    uint64_t framebuffer_bpp;            /* Framebuffer bits per pixel */
    uint64_t rsdp_addr;                  /* RSDP physical address */
    uint64_t mmap_addr;                  /* Memory map physical address */
    uint64_t mmap_length;                /* Memory map length */
    uint64_t mmap_entry_size;            /* Size of each memory map entry */
    uint64_t total_memory;               /* Total memory in bytes */
    uint64_t cpu_features[4];            /* CPU feature flags (CPUID leaf 1) */
    uint64_t boot_loader_name;           /* Physical address of bootloader name string */
    uint64_t cmdline_addr;               /* Physical address of command line */
} PACKED;

/* Boot stage type */
typedef enum {
    BOOT_STAGE_EARLY = 0,    /* Early assembly init */
    BOOT_STAGE_ARCH = 1,     /* Architecture init */
    BOOT_STAGE_MEMORY = 2,   /* Memory detection */
    BOOT_STAGE_PAGING = 3,   /* Paging setup */
    BOOT_STAGE_CPU = 4,      /* CPU features */
    BOOT_STAGE_APIC = 5,     /* APIC init */
    BOOT_STAGE_SMP = 6,      /* SMP boot */
    BOOT_STAGE_ACPI = 7,     /* ACPI init */
    BOOT_STAGE_DRIVERS = 8,  /* Driver init */
    BOOT_STAGE_FS = 9,       /* Filesystem init */
    BOOT_STAGE_READY = 10    /* System ready */
} boot_stage_t;

/* Boot status */
struct PACKED boot_status {
    uint64_t stage;
    uint64_t error_code;
    uint64_t last_success_addr;
    char     message[256];
} PACKED;

/* External boot info */
extern struct boot_info g_boot_info;
extern struct boot_status g_boot_status;

/* Boot console function pointers (early, before full driver init) */
typedef void (*boot_putchar_t)(char c);
typedef void (*boot_puts_t)(const char *s);
typedef void (*boot_printf_t)(const char *fmt, ...);

/* Early boot services */
void boot_early_init(void);
void boot_console_init(void);
void boot_putchar(char c);
void boot_puts(const char *s);
void boot_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void boot_halt(void);
void boot_panic(const char *msg) __attribute__((noreturn));

/* Memory detection */
void boot_detect_memory(void);
uint64_t boot_get_total_memory(void);
void boot_print_memory_map(void);

/* CPU detection */
void boot_detect_cpu(void);
uint32_t boot_get_cpu_features(void);
uint32_t boot_get_cpu_ext_features(void);
const char *boot_get_cpu_vendor(void);

/* Simple early allocator (bump allocator) */
void *boot_alloc(size_t size);
void *boot_alloc_aligned(size_t size, size_t align);
void boot_alloc_init(uint64_t start, uint64_t end);
uint64_t boot_alloc_get_used(void);

/* Parse multiboot tags */
void boot_parse_multiboot_tags(uint64_t addr);
void boot_parse_multiboot_info(uint64_t magic, uint64_t addr);

/* Transition to higher-half kernel */
void boot_enter_kernel(uint64_t entry, uint64_t stack);

/* Boot-time logging */
#define BOOT_LOG_OK       "[  OK  ] "
#define BOOT_LOG_FAIL     "[FAILED] "
#define BOOT_LOG_INFO     "[ INFO ] "
#define BOOT_LOG_WARN     "[ WARN ] "
#define BOOT_LOG_INIT     "[ INIT ] "

#endif /* AINOS_BOOT_BOOT_H */