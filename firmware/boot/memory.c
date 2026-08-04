/*
 * AinosOS - boot/memory.c
 * Memory detection via Multiboot2 memory map and BIOS E820
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <boot/multiboot.h>

/* Memory map entry */
struct memmap_entry {
    uint64_t base_addr;
    uint64_t length;
    uint32_t type;
    uint32_t acpi_extended;
};

/* Maximum number of memory map entries */
#define MAX_MEMMAP_ENTRIES 128

/* Global memory map storage */
static struct memmap_entry g_memmap[MAX_MEMMAP_ENTRIES];
static int g_memmap_count = 0;

/* Total memory */
static uint64_t g_total_memory = 0;
static uint64_t g_available_memory = 0;

/* Memory ranges for special regions */
#define MEM_BASE_LO         0x00000000
#define MEM_END_LO          0x0009FC00    /* End of usable low memory */
#define MEM_BASE_EBDA       0x0009FC00    /* EBDA start */
#define MEM_END_EBDA        0x000A0000    /* EBDA end */
#define MEM_BASE_VIDEO      0x000A0000    /* Video ROM */
#define MEM_END_VIDEO       0x000C0000    /* Video ROM end */
#define MEM_BASE_ROM        0x000C0000    /* Expansion ROMs */
#define MEM_END_ROM         0x00100000    /* Expansion ROMs end */
#define MEM_BASE_BIOS       0x000E0000    /* BIOS ROM */
#define MEM_END_BIOS        0x00100000    /* BIOS ROM end */
#define MEM_BASE_1MB        0x00100000    /* 1MB mark */

/*
 * String representation of memory type
 */
static const char *mem_type_string(uint32_t type) {
    switch (type) {
        case 1:  return "Available";
        case 2:  return "Reserved";
        case 3:  return "ACPI Reclaimable";
        case 4:  return "ACPI NVS";
        case 5:  return "Bad RAM";
        default: return "Unknown";
    }
}

/*
 * Parse the Multiboot2 memory map
 */
void boot_parse_memory_map(struct multiboot2_tag_mmap *mmap_tag) {
    uint32_t entry_size = mmap_tag->entry_size;
    int count = 0;

    boot_printf(BOOT_LOG_INIT "Parsing memory map...\n");

    /* Iterate over memory map entries */
    uint8_t *ptr = (uint8_t*)mmap_tag->entries;
    for (uint32_t i = 0; i < (mmap_tag->size - sizeof(struct multiboot2_tag_mmap)) / entry_size; i++) {
        struct multiboot2_mmap_entry *entry = (struct multiboot2_mmap_entry*)(ptr + i * entry_size);

        if (count >= MAX_MEMMAP_ENTRIES) {
            boot_printf(BOOT_LOG_WARN "Too many memory map entries, truncating\n");
            break;
        }

        /* Store the entry */
        g_memmap[count].base_addr      = entry->addr;
        g_memmap[count].length         = entry->len;
        g_memmap[count].type           = entry->type;
        g_memmap[count].acpi_extended  = entry->zero;
        count++;

        /* Accumulate totals */
        if (entry->type == MULTIBOOT2_MEMORY_AVAILABLE) {
            g_available_memory += entry->len;
        }

        uint64_t end = entry->addr + entry->len;
        if (end > g_total_memory) {
            g_total_memory = end;
        }
    }

    g_memmap_count = count;

    boot_printf(BOOT_LOG_OK "Memory map parsed: %d entries\n", count);
    boot_printf("  Total memory: %llu MB (%llu bytes)\n",
                g_total_memory / (1024 * 1024), g_total_memory);
    boot_printf("  Available:    %llu MB (%llu bytes)\n",
                g_available_memory / (1024 * 1024), g_available_memory);
}

/*
 * Print the memory map for debugging
 */
void boot_print_memory_map(void) {
    boot_printf("Memory map:\n");
    boot_printf("  %-18s %-18s %-12s %s\n", "Base", "End", "Length", "Type");

    for (int i = 0; i < g_memmap_count; i++) {
        uint64_t base = g_memmap[i].base_addr;
        uint64_t end  = base + g_memmap[i].length;
        uint64_t len  = g_memmap[i].length;

        boot_printf("  %016llX %016llX %010llX  %s\n",
                    base, end, len, mem_type_string(g_memmap[i].type));
    }
}

/*
 * Get total memory
 */
uint64_t boot_get_total_memory(void) {
    return g_total_memory;
}

/*
 * Get available memory
 */
uint64_t boot_get_available_memory(void) {
    return g_available_memory;
}

/*
 * Get memory map entry count
 */
int boot_get_memmap_count(void) {
    return g_memmap_count;
}

/*
 * Get a specific memory map entry
 */
const struct memmap_entry *boot_get_memmap_entry(int index) {
    if (index >= 0 && index < g_memmap_count) {
        return &g_memmap[index];
    }
    return NULL;
}

/*
 * Find the largest contiguous block of available memory
 */
uint64_t boot_find_largest_available_block(uint64_t *base_out) {
    uint64_t max_size = 0;
    uint64_t max_base = 0;

    for (int i = 0; i < g_memmap_count; i++) {
        if (g_memmap[i].type == MULTIBOOT2_MEMORY_AVAILABLE) {
            if (g_memmap[i].length > max_size) {
                max_size = g_memmap[i].length;
                max_base = g_memmap[i].base_addr;
            }
        }
    }

    if (base_out) {
        *base_out = max_base;
    }
    return max_size;
}

/*
 * Detect memory using Multiboot information
 * Called from the main boot initialization
 */
void boot_detect_memory(void) {
    /* Memory map is parsed from the Multiboot2 tags */
    /* See boot_parse_multiboot_tags() */
    if (g_memmap_count > 0) {
        boot_printf(BOOT_LOG_OK "Memory detection complete\n");
    } else {
        boot_printf(BOOT_LOG_WARN "No memory map found, using defaults\n");
        /* Fallback: assume 32MB of memory */
        g_total_memory = 32 * 1024 * 1024;
        g_available_memory = 28 * 1024 * 1024;
    }
}

/*
 * Get the usable memory region for kernel heap
 * Returns the start and size of the best region for kernel use
 */
void boot_get_kernel_memory_region(uint64_t *base, uint64_t *size) {
    /* Find the best region: large, above 1MB, preferably above 16MB */
    uint64_t best_base = 0;
    uint64_t best_size = 0;

    for (int i = 0; i < g_memmap_count; i++) {
        if (g_memmap[i].type != MULTIBOOT2_MEMORY_AVAILABLE) {
            continue;
        }

        uint64_t entry_base = g_memmap[i].base_addr;
        uint64_t entry_size = g_memmap[i].length;

        /* Skip regions below 1MB */
        if (entry_base + entry_size <= MEM_BASE_1MB) {
            continue;
        }

        /* Adjust region to start above 1MB if needed */
        if (entry_base < MEM_BASE_1MB) {
            uint64_t adjust = MEM_BASE_1MB - entry_base;
            if (adjust >= entry_size) continue;
            entry_base += adjust;
            entry_size -= adjust;
        }

        /* Pick the largest region */
        if (entry_size > best_size) {
            best_base = entry_base;
            best_size = entry_size;
        }
    }

    *base = best_base;
    *size = best_size;
}

/*
 * Check if a physical address range is usable
 */
int boot_is_memory_available(uint64_t base, uint64_t size) {
    uint64_t end = base + size;
    for (int i = 0; i < g_memmap_count; i++) {
        if (g_memmap[i].type == MULTIBOOT2_MEMORY_AVAILABLE) {
            uint64_t entry_start = g_memmap[i].base_addr;
            uint64_t entry_end   = entry_start + g_memmap[i].length;

            if (base >= entry_start && end <= entry_end) {
                return 1;
            }
        }
    }
    return 0;
}

/*
 * Mark a region as in use in the memory map
 */
void boot_reserve_memory(uint64_t base, uint64_t size) {
    /* This is a placeholder - actual reservation is done in the page allocator */
    /* We just log it for debugging */
    boot_printf("  Reserved memory: 0x%016llX - 0x%016llX (%llu KB)\n",
                base, base + size, size / 1024);
}

/*
 * Fill a memory map entry for a specific region
 */
int boot_fill_memmap_entry(int index, uint64_t base, uint64_t length, uint32_t type) {
    if (index >= 0 && index < MAX_MEMMAP_ENTRIES) {
        g_memmap[index].base_addr      = base;
        g_memmap[index].length         = length;
        g_memmap[index].type           = type;
        g_memmap[index].acpi_extended  = 0;
        if (index >= g_memmap_count) {
            g_memmap_count = index + 1;
        }
        return 0;
    }
    return -1;
}