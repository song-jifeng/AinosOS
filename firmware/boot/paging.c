/*
 * AinosOS - boot/paging.c
 * Page table initialization for x86_64 long mode
 *
 * Implements 4-level paging with:
 *   - Identity mapping for the first 4MB (boot code)
 *   - Higher-half mapping at 0xFFFF800000000000
 *   - Support for 2MB large pages and 4KB standard pages
 *   - NX bit support
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <boot/boot.h>

/* Page table entry bits */
#define PAGE_PRESENT        (1ULL << 0)
#define PAGE_RW             (1ULL << 1)
#define PAGE_USER           (1ULL << 2)
#define PAGE_WRITE_THROUGH  (1ULL << 3)
#define PAGE_CACHE_DISABLE  (1ULL << 4)
#define PAGE_ACCESSED       (1ULL << 5)
#define PAGE_DIRTY          (1ULL << 6)
#define PAGE_LARGE          (1ULL << 7)  /* 2MB or 1GB page */
#define PAGE_GLOBAL         (1ULL << 8)
#define PAGE_NX             (1ULL << 63) /* No-Execute */

/* Page table entry mask for physical address */
#define PAGE_ADDR_MASK      0x0000FFFFFFFFF000ULL
#define PAGE_ADDR_MASK_LARGE 0x0000FFFFFFFFFFC0ULL  /* For 2MB pages */

/* Page table levels */
#define PT_LEVEL_PML4       0
#define PT_LEVEL_PDPT       1
#define PT_LEVEL_PD         2
#define PT_LEVEL_PT         3

/* Number of entries per page table */
#define PT_ENTRIES          512

/* Higher half base */
#define HIGHER_HALF_BASE    0xFFFF800000000000ULL

/* Recursive mapping entry (PML4 last entry) */
#define RECURSIVE_ENTRY     511

/* Page table entry type */
typedef uint64_t page_table_entry_t;
typedef page_table_entry_t page_table_t[PT_ENTRIES] ALIGNED(PAGE_SIZE);

/* External page tables from boot.S */
extern page_table_t pml4;
extern page_table_t pdpt_low;
extern page_table_t pdpt_high;
extern page_table_t pd_low;

/* Kernel physical offset for virtual <-> physical conversion */
uint64_t _kernel_phys_offset = 0;

/* Total number of page frames */
static uint64_t total_pages = 0;

/* Page frame allocator bitmap */
static uint64_t *page_bitmap = NULL;
static uint64_t bitmap_size = 0;

/*
 * Initialize the kernel physical offset
 * This is the difference between virtual and physical addresses
 * for the higher-half mapping
 */
void paging_init_offset(void) {
    _kernel_phys_offset = HIGHER_HALF_BASE;
}

/*
 * Get the physical address from a virtual address
 */
uint64_t virt_to_phys(void *virt) {
    uint64_t vaddr = (uint64_t)virt;
    if (vaddr >= HIGHER_HALF_BASE) {
        return vaddr - HIGHER_HALF_BASE;
    }
    return vaddr;  /* Identity mapped */
}

/*
 * Get the virtual address from a physical address
 */
void *phys_to_virt(uint64_t phys) {
    return (void*)(phys + HIGHER_HALF_BASE);
}

/*
 * Extract the physical address from a page table entry
 */
static uint64_t pte_get_phys(page_table_entry_t entry) {
    return entry & PAGE_ADDR_MASK;
}

/*
 * Set a page table entry
 */
static void pte_set(page_table_entry_t *entry, uint64_t phys, uint64_t flags) {
    *entry = (phys & PAGE_ADDR_MASK) | flags;
}

/*
 * Initialize paging with identity mapping for boot and higher-half mapping
 *
 * This extends the minimal page tables set up in boot.S:
 *   - PML4[0] -> PDPT_low (identity map low 4GB via 2MB pages)
 *   - PML4[256] -> PDPT_high (higher half mapping)
 *   - PML4[511] -> PML4 (recursive mapping for easy page table manipulation)
 */
void paging_init(void) {
    page_table_entry_t entry;

    boot_printf(BOOT_LOG_INIT "Initializing page tables...\n");

    /* Set up the kernel physical offset */
    paging_init_offset();

    /* Set up recursive mapping: PML4[511] = PML4 physical address */
    pte_set(&pml4[RECURSIVE_ENTRY], (uint64_t)&pml4, PAGE_PRESENT | PAGE_RW);

    /* Identity map the first 4GB using 2MB pages */
    /* PML4[0] -> PDPT_low, map 0x00000000 - 0xFFFFFFFF */
    for (int i = 0; i < 512; i++) {
        /* For each PDPT entry, create a PD if needed */
        if (pdpt_low[i] == 0) {
            /* Allocate a page directory */
            page_table_t *pd = (page_table_t*)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
            if (!pd) {
                boot_panic("Failed to allocate page directory");
            }

            /* Clear the page directory */
            for (int j = 0; j < PT_ENTRIES; j++) {
                (*pd)[j] = 0;
            }

            /* Set up the PDPT entry */
            pte_set(&pdpt_low[i], (uint64_t)pd, PAGE_PRESENT | PAGE_RW);

            /* Fill the page directory with 2MB page entries */
            uint64_t base_addr = (uint64_t)i * 1024 * 1024 * 1024;  /* 1GB per PDPT entry */
            for (int j = 0; j < PT_ENTRIES; j++) {
                uint64_t page_addr = base_addr + (uint64_t)j * 2 * 1024 * 1024;  /* 2MB per PD entry */
                (*pd)[j] = page_addr | PAGE_PRESENT | PAGE_RW | PAGE_LARGE;
            }
        }
    }

    /* Set up higher-half mapping */
    /* PML4[256] -> PDPT_high (already mapped to same physical pages) */
    /* For now, the higher half points to the same page tables as the low half */
    /* This maps the first 1GB at 0xFFFF800000000000 */
    pte_set(&pml4[256], (uint64_t)&pdpt_low, PAGE_PRESENT | PAGE_RW);

    /* Load the page table base */
    write_cr3((uint64_t)&pml4);

    /* Enable NX (No-Execute) bit in EFER */
    uint64_t efer = read_msr(MSR_IA32_EFER);
    efer |= EFER_NXE;
    write_msr(MSR_IA32_EFER, efer);

    /* Enable Page Global Enable (PGE) in CR4 for global pages */
    uint64_t cr4 = read_cr4();
    cr4 |= CR4_PGE;
    write_cr4(cr4);

    boot_printf(BOOT_LOG_OK "Page tables initialized\n");
    boot_printf("  PML4 at:     0x%016llX (phys)\n", (uint64_t)&pml4);
    boot_printf("  Higher half: 0x%016llX\n", HIGHER_HALF_BASE);
    boot_printf("  Phys offset: 0x%016llX\n", _kernel_phys_offset);
}

/*
 * Map a single 4KB page in the page tables
 * This creates a new page table if needed (recursive mapping used)
 *
 * @param virt Virtual address to map
 * @param phys Physical address to map to
 * @param flags Page flags (PAGE_PRESENT, PAGE_RW, etc.)
 */
void paging_map_page(uint64_t virt, uint64_t phys, uint64_t flags) {
    /* Extract indices for each level */
    uint64_t pml4_idx = (virt >> 39) & 0x1FF;
    uint64_t pdpt_idx = (virt >> 30) & 0x1FF;
    uint64_t pd_idx   = (virt >> 21) & 0x1FF;
    uint64_t pt_idx   = (virt >> 12) & 0x1FF;

    /* Use recursive mapping to access page tables */
    /* PML4[511] points to PML4 itself */
    /* PDPT at PML4[511][pml4_idx] */
    /* PD at PML4[511][pml4_idx][pdpt_idx] */
    /* PT at PML4[511][pml4_idx][pdpt_idx][pd_idx] */

    /* Get the virtual address of the PML4 entry (via recursive mapping) */
    page_table_t *recursive_pml4 = (page_table_t*)(0xFFFFFFFFFFFFF000ULL);
    page_table_entry_t *pml4e = &(*recursive_pml4)[pml4_idx];

    /* Check if PDPT exists */
    uint64_t pdpt_phys = pte_get_phys(*pml4e);
    if (!(*pml4e & PAGE_PRESENT)) {
        /* Allocate a new PDPT */
        pdpt_phys = (uint64_t)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
        if (!pdpt_phys) {
            boot_panic("Failed to allocate PDPT");
        }
        /* Clear and set up */
        page_table_t *pdpt = (page_table_t*)(pdpt_phys + HIGHER_HALF_BASE);
        for (int i = 0; i < PT_ENTRIES; i++) {
            (*pdpt)[i] = 0;
        }
        pte_set(pml4e, pdpt_phys, PAGE_PRESENT | PAGE_RW);
        write_cr3(read_cr3());  /* Flush TLB */
    }

    /* Access PDPT via recursive mapping */
    page_table_t *recursive_pdpt = (page_table_t*)(0xFFFFFFFFE0000000ULL + (pml4_idx << 12));
    page_table_entry_t *pdpte = &(*recursive_pdpt)[pdpt_idx];

    /* Check if PD exists */
    uint64_t pd_phys = pte_get_phys(*pdpte);
    if (!(*pdpte & PAGE_PRESENT)) {
        pd_phys = (uint64_t)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
        if (!pd_phys) {
            boot_panic("Failed to allocate PD");
        }
        page_table_t *pd = (page_table_t*)(pd_phys + HIGHER_HALF_BASE);
        for (int i = 0; i < PT_ENTRIES; i++) {
            (*pd)[i] = 0;
        }
        pte_set(pdpte, pd_phys, PAGE_PRESENT | PAGE_RW);
        write_cr3(read_cr3());
    }

    /* Access PD via recursive mapping */
    page_table_t *recursive_pd = (page_table_t*)(0xFFFFFFC000000000ULL + (pml4_idx << 21) + (pdpt_idx << 12));
    page_table_entry_t *pde = &(*recursive_pd)[pd_idx];

    /* Check if PT exists */
    uint64_t pt_phys = pte_get_phys(*pde);
    if (!(*pde & PAGE_PRESENT)) {
        pt_phys = (uint64_t)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
        if (!pt_phys) {
            boot_panic("Failed to allocate PT");
        }
        page_table_t *pt = (page_table_t*)(pt_phys + HIGHER_HALF_BASE);
        for (int i = 0; i < PT_ENTRIES; i++) {
            (*pt)[i] = 0;
        }
        pte_set(pde, pt_phys, PAGE_PRESENT | PAGE_RW);
        write_cr3(read_cr3());
    }

    /* Access PT via recursive mapping */
    page_table_t *recursive_pt = (page_table_t*)(0xFFFFFF8000000000ULL + (pml4_idx << 30) + (pdpt_idx << 21) + (pd_idx << 12));
    pte_set(&(*recursive_pt)[pt_idx], phys, flags | PAGE_PRESENT | PAGE_RW);

    /* Flush TLB for this page */
    invlpg((void*)virt);
}

/*
 * Map a large (2MB) page
 */
void paging_map_large_page(uint64_t virt, uint64_t phys, uint64_t flags) {
    uint64_t pml4_idx = (virt >> 39) & 0x1FF;
    uint64_t pdpt_idx = (virt >> 30) & 0x1FF;
    uint64_t pd_idx   = (virt >> 21) & 0x1FF;

    page_table_t *recursive_pml4 = (page_table_t*)(0xFFFFFFFFFFFFF000ULL);
    page_table_entry_t *pml4e = &(*recursive_pml4)[pml4_idx];

    if (!(*pml4e & PAGE_PRESENT)) {
        uint64_t pdpt_phys = (uint64_t)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
        page_table_t *pdpt = (page_table_t*)(pdpt_phys + HIGHER_HALF_BASE);
        for (int i = 0; i < PT_ENTRIES; i++) (*pdpt)[i] = 0;
        pte_set(pml4e, pdpt_phys, PAGE_PRESENT | PAGE_RW);
        write_cr3(read_cr3());
    }

    page_table_t *recursive_pdpt = (page_table_t*)(0xFFFFFFFFE0000000ULL + (pml4_idx << 12));
    page_table_entry_t *pdpte = &(*recursive_pdpt)[pdpt_idx];

    if (!(*pdpte & PAGE_PRESENT)) {
        uint64_t pd_phys = (uint64_t)boot_alloc_aligned(PAGE_SIZE, PAGE_SIZE);
        page_table_t *pd = (page_table_t*)(pd_phys + HIGHER_HALF_BASE);
        for (int i = 0; i < PT_ENTRIES; i++) (*pd)[i] = 0;
        pte_set(pdpte, pd_phys, PAGE_PRESENT | PAGE_RW);
        write_cr3(read_cr3());
    }

    page_table_t *recursive_pd = (page_table_t*)(0xFFFFFFC000000000ULL + (pml4_idx << 21) + (pdpt_idx << 12));
    pte_set(&(*recursive_pd)[pd_idx], phys, flags | PAGE_PRESENT | PAGE_RW | PAGE_LARGE);

    /* Flush TLB */
    for (uint64_t addr = virt; addr < virt + 2 * 1024 * 1024; addr += PAGE_SIZE) {
        invlpg((void*)addr);
    }
}

/*
 * Unmap a page
 */
void paging_unmap_page(uint64_t virt) {
    uint64_t pml4_idx = (virt >> 39) & 0x1FF;
    uint64_t pdpt_idx = (virt >> 30) & 0x1FF;
    uint64_t pd_idx   = (virt >> 21) & 0x1FF;
    uint64_t pt_idx   = (virt >> 12) & 0x1FF;

    page_table_t *recursive_pt = (page_table_t*)(0xFFFFFF8000000000ULL + (pml4_idx << 30) + (pdpt_idx << 21) + (pd_idx << 12));
    (*recursive_pt)[pt_idx] = 0;

    invlpg((void*)virt);
}

/*
 * Check if a page is mapped
 */
int paging_is_mapped(uint64_t virt) {
    uint64_t pml4_idx = (virt >> 39) & 0x1FF;
    uint64_t pdpt_idx = (virt >> 30) & 0x1FF;
    uint64_t pd_idx   = (virt >> 21) & 0x1FF;
    uint64_t pt_idx   = (virt >> 12) & 0x1FF;

    page_table_t *recursive_pml4 = (page_table_t*)(0xFFFFFFFFFFFFF000ULL);
    if (!((*recursive_pml4)[pml4_idx] & PAGE_PRESENT)) return 0;

    page_table_t *recursive_pdpt = (page_table_t*)(0xFFFFFFFFE0000000ULL + (pml4_idx << 12));
    page_table_entry_t pdpte = (*recursive_pdpt)[pdpt_idx];
    if (!(pdpte & PAGE_PRESENT)) return 0;

    /* Check for 1GB page */
    if (pdpte & PAGE_LARGE) return 1;

    page_table_t *recursive_pd = (page_table_t*)(0xFFFFFFC000000000ULL + (pml4_idx << 21) + (pdpt_idx << 12));
    page_table_entry_t pde = (*recursive_pd)[pd_idx];
    if (!(pde & PAGE_PRESENT)) return 0;

    /* Check for 2MB page */
    if (pde & PAGE_LARGE) return 1;

    page_table_t *recursive_pt = (page_table_t*)(0xFFFFFF8000000000ULL + (pml4_idx << 30) + (pdpt_idx << 21) + (pd_idx << 12));
    return ((*recursive_pt)[pt_idx] & PAGE_PRESENT) ? 1 : 0;
}

/*
 * Initialize the page frame allocator
 * Uses a bitmap to track free physical pages
 */
void paging_init_allocator(uint64_t mem_start, uint64_t mem_size) {
    total_pages = mem_size / PAGE_SIZE;
    bitmap_size = (total_pages + 63) / 64;  /* 1 bit per page */

    boot_printf(BOOT_LOG_INIT "Initializing page frame allocator...\n");
    boot_printf("  Total memory: %llu MB (%llu pages)\n",
                mem_size / (1024 * 1024), total_pages);
    boot_printf("  Bitmap size: %llu bytes\n", bitmap_size * 8);

    /* Allocate bitmap from the start of available memory */
    page_bitmap = (uint64_t*)boot_alloc_aligned(bitmap_size * sizeof(uint64_t), PAGE_SIZE);
    if (!page_bitmap) {
        boot_panic("Failed to allocate page bitmap");
    }

    /* Mark all pages as free */
    for (uint64_t i = 0; i < bitmap_size; i++) {
        page_bitmap[i] = 0;
    }

    /* Mark the bitmap pages themselves as used */
    uint64_t bitmap_pages = (bitmap_size * sizeof(uint64_t) + PAGE_SIZE - 1) / PAGE_SIZE;
    uint64_t bitmap_start_page = (uint64_t)page_bitmap / PAGE_SIZE;
    for (uint64_t i = 0; i < bitmap_pages; i++) {
        paging_mark_page_used(bitmap_start_page + i);
    }

    boot_printf(BOOT_LOG_OK "Page frame allocator initialized\n");
}

/*
 * Mark a page frame as used
 */
void paging_mark_page_used(uint64_t page_num) {
    if (page_num < total_pages) {
        uint64_t word = page_num / 64;
        uint64_t bit  = page_num % 64;
        page_bitmap[word] |= (1ULL << bit);
    }
}

/*
 * Mark a page frame as free
 */
void paging_mark_page_free(uint64_t page_num) {
    if (page_num < total_pages) {
        uint64_t word = page_num / 64;
        uint64_t bit  = page_num % 64;
        page_bitmap[word] &= ~(1ULL << bit);
    }
}

/*
 * Check if a page is free
 */
int paging_is_page_free(uint64_t page_num) {
    if (page_num >= total_pages) return 0;
    uint64_t word = page_num / 64;
    uint64_t bit  = page_num % 64;
    return (page_bitmap[word] & (1ULL << bit)) == 0;
}

/*
 * Allocate a single physical page
 * Returns the physical address of the page, or 0 on failure
 */
uint64_t paging_alloc_page(void) {
    for (uint64_t i = 0; i < total_pages; i++) {
        if (paging_is_page_free(i)) {
            paging_mark_page_used(i);
            return i * PAGE_SIZE;
        }
    }
    return 0;  /* Out of memory */
}

/*
 * Free a physical page
 */
void paging_free_page(uint64_t phys_addr) {
    uint64_t page_num = phys_addr / PAGE_SIZE;
    paging_mark_page_free(page_num);
}

/*
 * Allocate a contiguous range of physical pages
 * Returns the physical address of the first page, or 0 on failure
 */
uint64_t paging_alloc_pages(uint64_t count) {
    uint64_t consecutive = 0;
    for (uint64_t i = 0; i < total_pages; i++) {
        if (paging_is_page_free(i)) {
            consecutive++;
            if (consecutive == count) {
                uint64_t start = i - count + 1;
                for (uint64_t j = 0; j < count; j++) {
                    paging_mark_page_used(start + j);
                }
                return start * PAGE_SIZE;
            }
        } else {
            consecutive = 0;
        }
    }
    return 0;
}

/*
 * Get the number of free pages
 */
uint64_t paging_get_free_count(void) {
    uint64_t count = 0;
    for (uint64_t i = 0; i < total_pages; i++) {
        if (paging_is_page_free(i)) {
            count++;
        }
    }
    return count;
}

/*
 * Get total number of pages
 */
uint64_t paging_get_total_pages(void) {
    return total_pages;
}

/*
 * Flush the entire TLB
 */
void paging_flush_tlb(void) {
    write_cr3(read_cr3());
}

/*
 * Dump the page table hierarchy for a given virtual address (debug)
 */
void paging_dump(uint64_t virt) {
    uint64_t idx[4] = {
        (virt >> 39) & 0x1FF,
        (virt >> 30) & 0x1FF,
        (virt >> 21) & 0x1FF,
        (virt >> 12) & 0x1FF
    };

    boot_printf("Page table walk for 0x%016llX:\n", virt);
    boot_printf("  PML4[%3llu] = 0x%016llX\n", idx[0], pml4[idx[0]]);

    page_table_t *recursive_pdpt = (page_table_t*)(0xFFFFFFFFE0000000ULL + (idx[0] << 12));
    boot_printf("  PDPT[%3llu] = 0x%016llX\n", idx[1], (*recursive_pdpt)[idx[1]]);

    page_table_t *recursive_pd = (page_table_t*)(0xFFFFFFC000000000ULL + (idx[0] << 21) + (idx[1] << 12));
    boot_printf("  PD[%3llu]   = 0x%016llX\n", idx[2], (*recursive_pd)[idx[2]]);

    if (!((*recursive_pd)[idx[2]] & PAGE_LARGE)) {
        page_table_t *recursive_pt = (page_table_t*)(0xFFFFFF8000000000ULL + (idx[0] << 30) + (idx[1] << 21) + (idx[2] << 12));
        boot_printf("  PT[%3llu]   = 0x%016llX\n", idx[3], (*recursive_pt)[idx[3]]);
    }
}