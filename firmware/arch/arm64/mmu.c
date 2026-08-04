/*
 * AinosOS - arch/arm64/mmu.c
 * AArch64 MMU initialization
 */

#include <types.h>
#include <macros.h>
#include <arch/arm64/registers.h>

/* Page table entry bits */
#define PTE_DESC_TYPE_MASK      (3UL << 0)
#define PTE_DESC_BLOCK          (1UL << 0)
#define PTE_DESC_PAGE           (3UL << 0)
#define PTE_DESC_TABLE          (3UL << 0)
#define PTE_VALID               (1UL << 0)
#define PTE_TABLE               (3UL << 0)
#define PTE_BLOCK               (1UL << 0)
#define PTE_PAGE                (3UL << 0)
#define PTE_ACCESS              (1UL << 10)
#define PTE_AF                  (1UL << 10)
#define PTE_NG                  (1UL << 11)
#define PTE_SH_INNER            (3UL << 8)
#define PTE_SH_OUTER            (2UL << 8)
#define PTE_AP_RW_EL1           (0UL << 6)
#define PTE_AP_RO_EL1           (1UL << 6)
#define PTE_AP_RW_EL0           (1UL << 6)
#define PTE_AP_RO_EL0           (3UL << 6)
#define PTE_ATTR_INDX_SHIFT     2
#define PTE_ATTR_INDX_MASK      (7UL << 2)
#define PTE_XN                  (1UL << 54)
#define PTE_CONTIGUOUS          (1UL << 52)
#define PTE_PXN                 (1UL << 53)

/* Page table levels */
#define L0_INDEX_SHIFT          39
#define L1_INDEX_SHIFT          30
#define L2_INDEX_SHIFT          21
#define L3_INDEX_SHIFT          12
#define PAGE_SHIFT              12
#define PAGE_SIZE               (1UL << PAGE_SHIFT)
#define PAGE_MASK               (PAGE_SIZE - 1)

/* Memory attributes (MAIR indices) */
#define MAIR_ATTR_NORMAL        0
#define MAIR_ATTR_DEVICE        1
#define MAIR_ATTR_NORMAL_NC     2

/* MAIR values */
#define MAIR_NORMAL             ((0xFFUL << (8 * MAIR_ATTR_NORMAL)) | \
                                 (0x44UL << (8 * MAIR_ATTR_DEVICE)))
#define MAIR_NORMAL_NC          (0x44UL << (8 * MAIR_ATTR_NORMAL_NC))

/* Page table entry type */
typedef uint64_t pte_t;

/* Number of entries per table */
#define PT_ENTRIES              512

/* Page table */
typedef pte_t page_table_t[PT_ENTRIES] ALIGNED(PAGE_SIZE);

/* Page tables */
static page_table_t pml4_el1 ALIGNED(PAGE_SIZE);
static page_table_t pdpt_el1 ALIGNED(PAGE_SIZE);
static page_table_t pd_el1 ALIGNED(PAGE_SIZE);
static page_table_t pt_el1 ALIGNED(PAGE_SIZE);

/*
 * Initialize the MMU with 4KB pages and 4-level page tables
 */
void mmu_init(void) {
    /* Set up MAIR (Memory Attribute Indirection Register) */
    write_mair_el1(MAIR_NORMAL);

    /* Set up TCR (Translation Control Register) */
    /* 4KB pages, 48-bit VA space, inner write-back cacheable */
    uint64_t tcr = TCR_TG0_4K | TCR_SH0_INNER |
                   TCR_ORGN0_WB_WA | TCR_IRGN0_WB_WA |
                   TCR_T0SZ(48) | TCR_PS_4TB;
    write_tcr_el1(tcr);

    /* Clear all page tables */
    for (int i = 0; i < PT_ENTRIES; i++) {
        pml4_el1[i] = 0;
        pdpt_el1[i] = 0;
        pd_el1[i] = 0;
        pt_el1[i] = 0;
    }

    /* Set up identity mapping for the first 2MB */
    /* L0: PML4[0] -> PDPT */
    pml4_el1[0] = ((uint64_t)&pdpt_el1) | PTE_TABLE;

    /* L1: PDPT[0] -> PD */
    pdpt_el1[0] = ((uint64_t)&pd_el1) | PTE_TABLE;

    /* L2: PD[0] -> 2MB block (identity map) */
    pd_el1[0] = (0x000000000ULL) | PTE_BLOCK | PTE_AF | PTE_AP_RW_EL1 | (MAIR_ATTR_NORMAL << 2);

    /* L2: PD[1] -> 2MB block (identity map 2MB-4MB) */
    pd_el1[1] = (0x200000ULL) | PTE_BLOCK | PTE_AF | PTE_AP_RW_EL1 | (MAIR_ATTR_NORMAL << 2);

    /* Set up device memory for UART and GIC */
    /* Map 0x2F000000 as device memory (GIC) */
    int l2_idx = (0x2F000000 >> 21) & 0x1FF;
    pd_el1[l2_idx] = (0x2F000000ULL) | PTE_BLOCK | PTE_AF | PTE_AP_RW_EL1 | (MAIR_ATTR_DEVICE << 2) | PTE_XN;

    /* Set higher half mapping (kernel at 0xFFFF800000000000) */
    /* PML4[256] = PDPT */
    pml4_el1[256] = ((uint64_t)&pdpt_el1) | PTE_TABLE;

    /* Set TTBR0_EL1 (lower half) */
    write_ttbr0_el1((uint64_t)&pml4_el1);

    /* Set TTBR1_EL1 (higher half) */
    write_ttbr1_el1((uint64_t)&pml4_el1);

    /* Ensure all table writes are visible */
    dsb();
    isb();

    /* Enable MMU */
    uint64_t sctlr = read_sctlr_el1();
    sctlr |= SCTLR_EL1_M | SCTLR_EL1_C | SCTLR_EL1_I;
    sctlr &= ~(1 << 1);  /* Clear A (alignment check) */
    write_sctlr_el1(sctlr);
    isb();
}

/*
 * Map a single 4KB page
 */
void mmu_map_page(uint64_t virt, uint64_t phys, uint64_t flags) {
    /* Implementation for 4KB page mapping */
    /* This would walk the page tables and create entries as needed */
    /* For now, identity mapping is sufficient */
    (void)virt;
    (void)phys;
    (void)flags;
}

/*
 * Create a 2MB block mapping
 */
void mmu_map_block(uint64_t virt, uint64_t phys, uint64_t flags) {
    /* Implementation for 2MB block mapping */
    (void)virt;
    (void)phys;
    (void)flags;
}

/*
 * Ensure cache coherency
 */
void mmu_clean_invalidate_cache(void *addr, size_t size) {
    uint64_t *ptr = (uint64_t*)((uint64_t)addr & ~(64 - 1));
    uint64_t *end = (uint64_t*)((uint64_t)addr + size);

    while (ptr < end) {
        dc_civac(ptr);
        ptr += 64 / sizeof(uint64_t);
    }
    dsb();
    isb();
}

/*
 * Invalidate instruction cache
 */
void mmu_invalidate_icache(void) {
    __asm__ volatile("ic ialluis" ::: "memory");
    dsb();
    isb();
}

/*
 * Read the current translation table base
 */
uint64_t mmu_get_ttbr0(void) {
    return read_ttbr0_el1();
}

/*
 * Set the translation table base (for address space switching)
 */
void mmu_set_ttbr0(uint64_t ttbr) {
    write_ttbr0_el1(ttbr);
    isb();
}

/*
 * Get the physical address of a virtual address (if mapped)
 */
uint64_t mmu_virt_to_phys(uint64_t virt) {
    /* For identity mapping, virt == phys */
    return virt;
}

/*
 * Get the virtual address of a physical address
 */
uint64_t mmu_phys_to_virt(uint64_t phys) {
    /* For identity mapping, phys == virt */
    return phys;
}

/*
 * ARM64 exception handlers (C level)
 */
void arm64_exception_default(uint64_t esr, uint64_t far, uint64_t elr) {
    /* Default exception handler */
    (void)esr;
    (void)far;
    (void)elr;
    /* In a real system, this would log and panic */
    for (;;) { wfi(); }
}

void arm64_irq_default(void) {
    /* Default IRQ handler */
    /* ACK and EOI via GIC */
    uint32_t iar = *(volatile uint32_t*)(GIC_ICC_IAR);
    (void)iar;
    *(volatile uint32_t*)(GIC_ICC_EOIR) = iar;
}

void arm64_fiq_default(void) {
    /* Default FIQ handler */
}

void arm64_serr_default(void) {
    /* Default SError handler */
}

void arm64_sync_handler(uint64_t esr, uint64_t far, uint64_t elr) {
    /* Synchronous exception handler at EL1 */
    uint32_t ec = (esr >> 26) & 0x3F;
    (void)far;
    (void)elr;

    switch (ec) {
        case 0x25:  /* Data abort */
        case 0x24:  /* Instruction abort */
            /* Page fault - handle or panic */
            break;
        default:
            break;
    }
}

void arm64_syscall_handler(uint64_t esr, uint64_t far) {
    /* System call handler (SVC from EL0) */
    uint16_t imm = esr & 0xFFFF;
    (void)far;
    (void)imm;
    /* In a real system, dispatch to syscall table */
}

void secondary_cpu_init(void) {
    /* Secondary CPU initialization */
    mmu_init();
    /* Enable interrupts and start scheduling */
}