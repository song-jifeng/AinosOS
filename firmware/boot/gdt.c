/*
 * AinosOS - boot/gdt.c
 * Global Descriptor Table initialization for x86_64
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/registers.h>

/* GDT entry structure */
struct PACKED gdt_entry {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t  base_mid;
    uint8_t  access;
    uint8_t  granularity;
    uint8_t  base_high;
};

/* GDT entry for 64-bit mode */
struct PACKED gdt_entry_long {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t  base_mid;
    uint8_t  access;
    uint8_t  granularity;
    uint8_t  base_high;
    uint32_t base_upper;
    uint32_t reserved;
};

/* System segment descriptor (for TSS) */
struct PACKED tss_descriptor {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t  base_mid;
    uint8_t  access;
    uint8_t  granularity;
    uint8_t  base_high;
    uint32_t base_upper;
    uint32_t reserved;
};

/* GDT pointer */
struct PACKED gdtr {
    uint16_t limit;
    uint64_t base;
};

/* Task State Segment */
struct PACKED tss {
    uint32_t reserved0;
    uint64_t rsp[3];
    uint64_t reserved1;
    uint64_t ist[7];
    uint64_t reserved2;
    uint16_t reserved3;
    uint16_t iomap_base;
} ALIGNED(16);

/* Aligned GDT */
static struct gdt_entry_long gdt[8] ALIGNED(16);
static struct tss tss_entry ALIGNED(16);

/* GDT descriptor access flags */
#define GDT_ACCESS_PRESENT      (1 << 7)
#define GDT_ACCESS_DPL0         (0 << 5)
#define GDT_ACCESS_DPL1         (1 << 5)
#define GDT_ACCESS_DPL2         (2 << 5)
#define GDT_ACCESS_DPL3         (3 << 5)
#define GDT_ACCESS_DPL_MASK     (3 << 5)
#define GDT_ACCESS_SYSTEM       (0 << 4)  /* S = 0 */
#define GDT_ACCESS_CODE_DATA    (1 << 4)  /* S = 1 */
#define GDT_ACCESS_EXECUTABLE   (1 << 3)  /* For code segments */
#define GDT_ACCESS_DIRECTION    (1 << 2)  /* Direction for data, conforming for code */
#define GDT_ACCESS_RW           (1 << 1)  /* Readable (code) / Writable (data) */
#define GDT_ACCESS_ACCESSED     (1 << 0)

/* GDT granularity flags */
#define GDT_GRAN_4K             (1 << 7)
#define GDT_GRAN_32BIT          (1 << 6)  /* D/B bit */
#define GDT_GRAN_LONG           (1 << 5)  /* L bit (64-bit code) */
#define GDT_GRAN_AVAILABLE      (1 << 4)

/* GDT selector indices */
#define GDT_NULL        0x00
#define GDT_CODE64      0x08  /* Ring 0 64-bit code */
#define GDT_DATA64      0x10  /* Ring 0 64-bit data */
#define GDT_CODE64_USER 0x18  /* Ring 3 64-bit code */
#define GDT_DATA64_USER 0x20  /* Ring 3 64-bit data */
#define GDT_TSS         0x28  /* TSS */

/*
 * Create a GDT entry for a long mode code or data segment
 */
static void gdt_set_entry(int index, uint8_t access, uint8_t granularity) {
    gdt[index].limit_low    = 0xFFFF;
    gdt[index].base_low     = 0;
    gdt[index].base_mid     = 0;
    gdt[index].access       = access;
    gdt[index].granularity  = granularity | 0x0F;  /* Limit high bits = 0xF */
    gdt[index].base_high    = 0;
    gdt[index].base_upper   = 0;
    gdt[index].reserved     = 0;
}

/*
 * Create a TSS descriptor in the GDT
 */
static void gdt_set_tss(int index, uint64_t tss_addr, uint32_t tss_size) {
    struct tss_descriptor *desc = (struct tss_descriptor*)&gdt[index];

    desc->limit_low     = tss_size & 0xFFFF;
    desc->base_low      = tss_addr & 0xFFFF;
    desc->base_mid      = (tss_addr >> 16) & 0xFF;
    desc->access        = GDT_ACCESS_PRESENT | GDT_ACCESS_DPL0 | GDT_ACCESS_EXECUTABLE | GDT_ACCESS_ACCESSED;
    desc->access        = 0x89;  /* Present, DPL0, 32-bit TSS available */
    desc->granularity   = ((tss_size >> 16) & 0x0F) | 0x00;
    desc->base_high     = (tss_addr >> 24) & 0xFF;
    desc->base_upper    = (tss_addr >> 32) & 0xFFFFFFFF;
    desc->reserved      = 0;
}

/*
 * Initialize the TSS with stack pointers
 */
void tss_init(uint64_t stack0, uint64_t stack1, uint64_t stack2) {
    tss_entry.reserved0     = 0;
    tss_entry.rsp[0]        = stack0;  /* Ring 0 stack */
    tss_entry.rsp[1]        = stack1;  /* Ring 1 stack */
    tss_entry.rsp[2]        = stack2;  /* Ring 2 stack */
    tss_entry.reserved1     = 0;
    tss_entry.ist[0]        = 0;       /* IST1 */
    tss_entry.ist[1]        = 0;       /* IST2 */
    tss_entry.ist[2]        = 0;       /* IST3 */
    tss_entry.ist[3]        = 0;       /* IST4 */
    tss_entry.ist[4]        = 0;       /* IST5 */
    tss_entry.ist[5]        = 0;       /* IST6 */
    tss_entry.ist[6]        = 0;       /* IST7 */
    tss_entry.reserved2     = 0;
    tss_entry.reserved3     = 0;
    tss_entry.iomap_base    = sizeof(struct tss);
}

/*
 * Get the TSS pointer
 */
struct tss *tss_get(void) {
    return &tss_entry;
}

/*
 * Initialize the GDT for 64-bit long mode
 *
 * Sets up:
 *   - NULL descriptor
 *   - Ring 0 64-bit code segment
 *   - Ring 0 64-bit data segment
 *   - Ring 3 64-bit code segment
 *   - Ring 3 64-bit data segment
 *   - TSS descriptor
 */
void gdt_init(void) {
    /* Set up standard GDT entries */
    gdt_set_entry(0, 0, 0);                                          /* NULL */
    gdt_set_entry(1, GDT_ACCESS_PRESENT | GDT_ACCESS_CODE_DATA |     /* Ring 0 Code */
                       GDT_ACCESS_EXECUTABLE | GDT_ACCESS_RW,
                       GDT_GRAN_LONG | GDT_GRAN_4K);
    gdt_set_entry(2, GDT_ACCESS_PRESENT | GDT_ACCESS_CODE_DATA |     /* Ring 0 Data */
                       GDT_ACCESS_RW,
                       GDT_GRAN_4K);
    gdt_set_entry(3, GDT_ACCESS_PRESENT | GDT_ACCESS_DPL3 |          /* Ring 3 Code */
                       GDT_ACCESS_CODE_DATA | GDT_ACCESS_EXECUTABLE | GDT_ACCESS_RW,
                       GDT_GRAN_LONG | GDT_GRAN_4K);
    gdt_set_entry(4, GDT_ACCESS_PRESENT | GDT_ACCESS_DPL3 |          /* Ring 3 Data */
                       GDT_ACCESS_CODE_DATA | GDT_ACCESS_RW,
                       GDT_GRAN_4K);

    /* Set up TSS descriptor */
    tss_init(0, 0, 0);  /* Stacks will be set during scheduling init */
    gdt_set_tss(5, (uint64_t)&tss_entry, sizeof(tss_entry));

    /* Load GDT */
    struct gdtr gdtr_struct;
    gdtr_struct.limit = sizeof(gdt) - 1;
    gdtr_struct.base  = (uint64_t)&gdt;
    lgdt(&gdtr_struct);

    /* Reload segment registers */
    __asm__ volatile(
        "pushq %0;"
        "leaq 1f(%%rip), %%rax;"
        "pushq %%rax;"
        "lretq;"
        "1:"
        "movw %1, %%ds;"
        "movw %1, %%es;"
        "movw %1, %%fs;"
        "movw %1, %%gs;"
        "movw %1, %%ss;"
        :: "i"(GDT_CODE64), "r"((uint16_t)GDT_DATA64)
        : "rax", "memory");
}

/*
 * Load TSS (must be called after GDT init and TSS init)
 */
void gdt_load_tss(void) {
    ltr(GDT_TSS);
}

/*
 * Set the ring 0 stack pointer in the TSS
 */
void tss_set_stack0(uint64_t stack) {
    tss_entry.rsp[0] = stack;
}

/*
 * Set an IST (Interrupt Stack Table) entry
 */
void tss_set_ist(int index, uint64_t stack) {
    if (index >= 0 && index < 7) {
        tss_entry.ist[index] = stack;
    }
}

/*
 * Get current GDT entry value (for debugging)
 */
uint64_t gdt_get_entry(int index) {
    if (index >= 0 && index < 8) {
        return *(uint64_t*)&gdt[index];
    }
    return 0;
}

/*
 * Print GDT contents (for early boot debugging)
 */
void gdt_dump(void) {
    boot_printf("GDT dump:\n");
    for (int i = 0; i < 6; i++) {
        uint64_t entry = gdt_get_entry(i);
        boot_printf("  [%d] 0x%016llX\n", i, entry);
    }
    boot_printf("  TSS addr: 0x%016llX, size: %d\n",
                (uint64_t)&tss_entry, sizeof(tss_entry));
}