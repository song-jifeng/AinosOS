/*
 * AinosOS - boot/acpi.c
 * ACPI table parsing and initialization
 *
 * Parses the Root System Description Pointer (RSDP) and
 * walks the ACPI table tree to find MADT, HPET, FADT, etc.
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <boot/multiboot.h>

/* ACPI signature lengths */
#define ACPI_RSDP_SIG        "RSD PTR "
#define ACPI_RSDP_SIG_LEN    8
#define ACPI_SDT_SIG_LEN     4

/* ACPI 1.0 RSDP structure */
struct PACKED acpi_rsdp_v1 {
    char     signature[8];
    uint8_t  checksum;
    char     oem_id[6];
    uint8_t  revision;
    uint32_t rsdt_addr;
};

/* ACPI 2.0+ RSDP structure */
struct PACKED acpi_rsdp_v2 {
    char     signature[8];
    uint8_t  checksum;
    char     oem_id[6];
    uint8_t  revision;
    uint32_t rsdt_addr;
    uint32_t length;
    uint64_t xsdt_addr;
    uint8_t  ext_checksum;
    uint8_t  reserved[3];
};

/* ACPI SDT (System Description Table) header */
struct PACKED acpi_sdt_header {
    char     signature[4];
    uint32_t length;
    uint8_t  revision;
    uint8_t  checksum;
    char     oem_id[6];
    char     oem_table_id[8];
    uint32_t oem_revision;
    uint32_t creator_id;
    uint32_t creator_revision;
};

/* RSDT (Root System Description Table) */
struct PACKED acpi_rsdt {
    struct acpi_sdt_header header;
    uint32_t entry_ptrs[];  /* Array of 32-bit physical addresses */
};

/* XSDT (Extended System Description Table) */
struct PACKED acpi_xsdt {
    struct acpi_sdt_header header;
    uint64_t entry_ptrs[];  /* Array of 64-bit physical addresses */
};

/* MADT (Multiple APIC Description Table) */
struct PACKED acpi_madt {
    struct acpi_sdt_header header;
    uint32_t lapic_addr;
    uint32_t flags;
};

/* MADT entry types */
#define MADT_TYPE_LAPIC             0
#define MADT_TYPE_IOAPIC            1
#define MADT_TYPE_INTERRUPT_OVERRIDE 2
#define MADT_TYPE_NMI_SOURCE        3
#define MADT_TYPE_LAPIC_NMI         4
#define MADT_TYPE_LAPIC_ADDR_OVERRIDE 5
#define MADT_TYPE_IO_SAPIC          6
#define MADT_TYPE_LSAPIC            7
#define MADT_TYPE_PLATFORM_INTERRUPT 8

/* MADT entry header */
struct PACKED madt_entry_header {
    uint8_t type;
    uint8_t length;
};

/* MADT LAPIC entry */
struct PACKED madt_lapic_entry {
    struct madt_entry_header header;
    uint8_t  processor_id;
    uint8_t  apic_id;
    uint32_t flags;
};

/* MADT I/O APIC entry */
struct PACKED madt_ioapic_entry {
    struct madt_entry_header header;
    uint8_t  ioapic_id;
    uint8_t  reserved;
    uint32_t ioapic_addr;
    uint32_t gsi_base;
};

/* MADT interrupt override entry */
struct PACKED madt_int_override {
    struct madt_entry_header header;
    uint8_t  bus;
    uint8_t  source;
    uint32_t gsi;
    uint16_t flags;
};

/* HPET table */
struct PACKED acpi_hpet {
    struct acpi_sdt_header header;
    uint32_t event_timer_block_id;
    uint8_t  base_address[8];  /* Actually a struct acpi_generic_address */
    uint8_t  hpet_number;
    uint16_t min_clock_tick;
    uint8_t  page_protection;
};

/* FADT (Fixed ACPI Description Table) */
struct PACKED acpi_fadt {
    struct acpi_sdt_header header;
    uint32_t firmware_ctrl;
    uint32_t dsdt_addr;
    uint8_t  reserved;
    uint8_t  preferred_pm_profile;
    uint16_t sci_int;
    uint32_t smi_cmd;
    uint8_t  acpi_enable;
    uint8_t  acpi_disable;
    uint8_t  s4bios_req;
    uint8_t  pstate_cnt;
    uint32_t pm1a_evt_blk;
    uint32_t pm1b_evt_blk;
    uint32_t pm1a_cnt_blk;
    uint32_t pm1b_cnt_blk;
    uint32_t pm2_cnt_blk;
    uint32_t pm_tmr_blk;
    uint32_t gpe0_blk;
    uint32_t gpe1_blk;
    uint8_t  pm1_evt_len;
    uint8_t  pm1_cnt_len;
    uint8_t  pm2_cnt_len;
    uint8_t  pm_tmr_len;
    uint8_t  gpe0_blk_len;
    uint8_t  gpe1_blk_len;
    uint8_t  gpe1_base;
    uint8_t  cst_cnt;
    uint16_t p_lvl2_lat;
    uint16_t p_lvl3_lat;
    uint16_t flush_size;
    uint16_t flush_stride;
    uint8_t  duty_offset;
    uint8_t  duty_width;
    uint8_t  day_alrm;
    uint8_t  mon_alrm;
    uint8_t  century;
    uint16_t iapc_boot_arch;
    uint8_t  reserved2;
    uint32_t flags;
    uint8_t  reset_reg[12];
    uint8_t  reset_value;
    uint8_t  reserved3[3];
    uint64_t x_firmware_ctrl;
    uint64_t x_dsdt;
    uint8_t  x_pm1a_evt_blk[12];
    uint8_t  x_pm1b_evt_blk[12];
    uint8_t  x_pm1a_cnt_blk[12];
    uint8_t  x_pm1b_cnt_blk[12];
    uint8_t  x_pm2_cnt_blk[12];
    uint8_t  x_pm_tmr_blk[12];
    uint8_t  x_gpe0_blk[12];
    uint8_t  x_gpe1_blk[12];
};

/* Global ACPI state */
static struct acpi_rsdp_v2 *g_rsdp = NULL;
static struct acpi_rsdt *g_rsdt = NULL;
static struct acpi_xsdt *g_xsdt = NULL;
static int g_acpi_revision = 0;
static int g_acpi_available = 0;

/* MADT information */
static struct acpi_madt *g_madt = NULL;
static uint32_t g_lapic_addr = 0;
static uint32_t g_ioapic_addr = 0;
static uint32_t g_ioapic_gsi_base = 0;
static int g_lapic_count = 0;
static int g_ioapic_count = 0;

/*
 * Calculate ACPI checksum
 */
static uint8_t acpi_checksum(const void *table, uint32_t length) {
    uint8_t sum = 0;
    const uint8_t *bytes = (const uint8_t*)table;
    for (uint32_t i = 0; i < length; i++) {
        sum += bytes[i];
    }
    return sum;
}

/*
 * Find the RSDP by searching BIOS memory areas
 * The RSDP is in EBDA (0x80000-0x9FFFF) or BIOS area (0xE0000-0xFFFFF)
 */
static struct acpi_rsdp_v2 *acpi_find_rsdp(void) {
    /* Search in the BIOS ROM area first */
    uint8_t *bios_start = (uint8_t*)(uint64_t)0xE0000;
    uint8_t *bios_end   = (uint8_t*)(uint64_t)0xFFFFF;

    /* Check if Multiboot provided RSDP */
    if (g_rsdp) {
        return g_rsdp;
    }

    /* Search BIOS area */
    for (uint8_t *addr = bios_start; addr < bios_end; addr += 16) {
        if (*(uint64_t*)addr == *(uint64_t*)ACPI_RSDP_SIG) {
            return (struct acpi_rsdp_v2*)addr;
        }
    }

    /* Search EBDA area */
    uint8_t *ebda_start = (uint8_t*)(uint64_t)0x80000;
    uint8_t *ebda_end   = (uint8_t*)(uint64_t)0x9FFFF;

    for (uint8_t *addr = ebda_start; addr < ebda_end; addr += 16) {
        if (*(uint64_t*)addr == *(uint64_t*)ACPI_RSDP_SIG) {
            return (struct acpi_rsdp_v2*)addr;
        }
    }

    return NULL;
}

/*
 * Verify the RSDP checksum
 */
static int acpi_verify_rsdp(struct acpi_rsdp_v2 *rsdp) {
    /* Check v1 checksum (first 20 bytes) */
    if (acpi_checksum(rsdp, 20) != 0) {
        return 0;
    }

    /* Check v2 extended checksum if applicable */
    if (rsdp->revision >= 2) {
        if (acpi_checksum(rsdp, rsdp->length) != 0) {
            return 0;
        }
    }

    return 1;
}

/*
 * Verify an SDT header checksum
 */
static int acpi_verify_sdt(struct acpi_sdt_header *header) {
    return acpi_checksum(header, header->length) == 0;
}

/*
 * Find an ACPI table by signature
 */
static void *acpi_find_table(const char *signature) {
    if (!g_acpi_available) return NULL;

    uint32_t entry_count;

    if (g_xsdt) {
        /* XSDT: 64-bit entries */
        entry_count = (g_xsdt->header.length - sizeof(struct acpi_sdt_header)) / 8;
        for (uint32_t i = 0; i < entry_count; i++) {
            struct acpi_sdt_header *header = (struct acpi_sdt_header*)(uint64_t)g_xsdt->entry_ptrs[i];
            if (*(uint32_t*)header->signature == *(uint32_t*)signature) {
                if (acpi_verify_sdt(header)) {
                    return header;
                }
            }
        }
    } else if (g_rsdt) {
        /* RSDT: 32-bit entries */
        entry_count = (g_rsdt->header.length - sizeof(struct acpi_sdt_header)) / 4;
        for (uint32_t i = 0; i < entry_count; i++) {
            struct acpi_sdt_header *header = (struct acpi_sdt_header*)(uint64_t)g_rsdt->entry_ptrs[i];
            if (*(uint32_t*)header->signature == *(uint32_t*)signature) {
                if (acpi_verify_sdt(header)) {
                    return header;
                }
            }
        }
    }

    return NULL;
}

/*
 * Parse the MADT (Multiple APIC Description Table)
 */
static void acpi_parse_madt(void) {
    g_madt = (struct acpi_madt*)acpi_find_table("APIC");
    if (!g_madt) {
        boot_printf(BOOT_LOG_WARN "MADT not found\n");
        return;
    }

    g_lapic_addr = g_madt->lapic_addr;

    boot_printf(BOOT_LOG_INIT "Parsing MADT...\n");
    boot_printf("  LAPIC addr: 0x%08X\n", g_lapic_addr);

    /* Walk through MADT entries */
    uint8_t *entry_start = (uint8_t*)g_madt + sizeof(struct acpi_madt);
    uint8_t *entry_end   = (uint8_t*)g_madt + g_madt->header.length;
    uint8_t *ptr         = entry_start;

    while (ptr < entry_end) {
        struct madt_entry_header *entry = (struct madt_entry_header*)ptr;

        switch (entry->type) {
            case MADT_TYPE_LAPIC: {
                struct madt_lapic_entry *lapic = (struct madt_lapic_entry*)ptr;
                boot_printf("  LAPIC: proc=%u, apic_id=%u, flags=0x%08X\n",
                            lapic->processor_id, lapic->apic_id, lapic->flags);
                if (lapic->flags & 1) {  /* Processor Enabled */
                    g_lapic_count++;
                }
                break;
            }

            case MADT_TYPE_IOAPIC: {
                struct madt_ioapic_entry *ioapic = (struct madt_ioapic_entry*)ptr;
                boot_printf("  I/O APIC: id=%u, addr=0x%08X, gsi_base=%u\n",
                            ioapic->ioapic_id, ioapic->ioapic_addr, ioapic->gsi_base);
                if (g_ioapic_count == 0) {
                    g_ioapic_addr = ioapic->ioapic_addr;
                    g_ioapic_gsi_base = ioapic->gsi_base;
                }
                g_ioapic_count++;
                break;
            }

            case MADT_TYPE_INTERRUPT_OVERRIDE: {
                struct madt_int_override *override = (struct madt_int_override*)ptr;
                boot_printf("  IRQ override: bus=%u, source=%u, gsi=%u, flags=0x%04X\n",
                            override->bus, override->source, override->gsi, override->flags);
                break;
            }

            case MADT_TYPE_LAPIC_NMI: {
                boot_printf("  LAPIC NMI entry\n");
                break;
            }

            case MADT_TYPE_LAPIC_ADDR_OVERRIDE: {
                uint64_t *override_addr = (uint64_t*)(ptr + 2);
                boot_printf("  LAPIC addr override: 0x%016llX\n", *override_addr);
                g_lapic_addr = (uint32_t)*override_addr;
                break;
            }

            default:
                boot_printf("  MADT entry type %u (len=%u)\n", entry->type, entry->length);
                break;
        }

        ptr += entry->length;
    }

    boot_printf(BOOT_LOG_OK "MADT: %u LAPICs, %u I/O APICs\n", g_lapic_count, g_ioapic_count);
}

/*
 * Parse the HPET table
 */
static void acpi_parse_hpet(void) {
    struct acpi_hpet *hpet = (struct acpi_hpet*)acpi_find_table("HPET");
    if (!hpet) {
        boot_printf(BOOT_LOG_WARN "HPET not found\n");
        return;
    }

    boot_printf(BOOT_LOG_INIT "HPET: block_id=0x%08X, number=%u\n",
                hpet->event_timer_block_id, hpet->hpet_number);
}

/*
 * Initialize ACPI
 */
void acpi_init(void) {
    struct acpi_rsdp_v2 *rsdp;

    boot_printf(BOOT_LOG_INIT "Initializing ACPI...\n");

    /* Find the RSDP */
    rsdp = acpi_find_rsdp();
    if (!rsdp) {
        boot_printf(BOOT_LOG_FAIL "RSDP not found\n");
        return;
    }

    /* Verify RSDP checksum */
    if (!acpi_verify_rsdp(rsdp)) {
        boot_printf(BOOT_LOG_FAIL "RSDP checksum failed\n");
        return;
    }

    g_rsdp = rsdp;
    g_acpi_revision = rsdp->revision;

    boot_printf("  RSDP at 0x%016llX, revision %u\n", (uint64_t)rsdp, g_acpi_revision);
    boot_printf("  OEM ID: %.6s\n", rsdp->oem_id);

    /* Get RSDT or XSDT */
    if (g_acpi_revision >= 2 && rsdp->xsdt_addr) {
        g_xsdt = (struct acpi_xsdt*)(uint64_t)rsdp->xsdt_addr;
        if (!acpi_verify_sdt(&g_xsdt->header)) {
            boot_printf(BOOT_LOG_FAIL "XSDT checksum failed\n");
            g_xsdt = NULL;
        } else {
            boot_printf("  XSDT at 0x%016llX\n", (uint64_t)g_xsdt);
        }
    }

    if (!g_xsdt && rsdp->rsdt_addr) {
        g_rsdt = (struct acpi_rsdt*)(uint64_t)rsdp->rsdt_addr;
        if (!acpi_verify_sdt(&g_rsdt->header)) {
            boot_printf(BOOT_LOG_FAIL "RSDT checksum failed\n");
            g_rsdt = NULL;
        } else {
            boot_printf("  RSDT at 0x%016llX\n", (uint64_t)g_rsdt);
        }
    }

    if (!g_rsdt && !g_xsdt) {
        boot_printf(BOOT_LOG_FAIL "No RSDT or XSDT available\n");
        return;
    }

    g_acpi_available = 1;

    /* Parse known tables */
    acpi_parse_madt();
    acpi_parse_hpet();

    boot_printf(BOOT_LOG_OK "ACPI initialized\n");
}

/*
 * Get the LAPIC address from ACPI
 */
uint32_t acpi_get_lapic_addr(void) {
    return g_lapic_addr;
}

/*
 * Get the I/O APIC address from ACPI
 */
uint32_t acpi_get_ioapic_addr(void) {
    return g_ioapic_addr;
}

/*
 * Get the number of LAPICs found
 */
int acpi_get_lapic_count(void) {
    return g_lapic_count;
}

/*
 * Get the number of I/O APICs found
 */
int acpi_get_ioapic_count(void) {
    return g_ioapic_count;
}

/*
 * Check if ACPI is available
 */
int acpi_is_available(void) {
    return g_acpi_available;
}

/*
 * Get the RSDP revision
 */
int acpi_get_revision(void) {
    return g_acpi_revision;
}

/*
 * Get the RSDP
 */
struct acpi_rsdp_v2 *acpi_get_rsdp(void) {
    return g_rsdp;
}

/*
 * Reboot the system using ACPI RESET register
 */
void acpi_reset(void) {
    struct acpi_fadt *fadt = (struct acpi_fadt*)acpi_find_table("FACP");
    if (!fadt) {
        /* Fallback to triple fault reset */
        triple_fault_reset();
        return;
    }

    /* Check if reset register is supported */
    if (fadt->reset_reg[0] == 0) {  /* Address space ID = 0 means not supported */
        triple_fault_reset();
        return;
    }

    /* Read the reset register info */
    uint8_t addr_space = fadt->reset_reg[0];
    uint8_t bit_width  = fadt->reset_reg[1];
    uint8_t bit_offset = fadt->reset_reg[2];
    uint64_t address   = *(uint64_t*)&fadt->reset_reg[4];

    /* Write the reset value to the reset register */
    switch (addr_space) {
        case 0:  /* System memory */
            *(volatile uint8_t*)(uint64_t)address = fadt->reset_value;
            break;
        case 1:  /* System I/O */
            io_outb((uint16_t)address, fadt->reset_value);
            break;
        case 2:  /* PCI config space */
            /* Not implemented */
            break;
        default:
            triple_fault_reset();
            break;
    }

    /* Halt if reset didn't work */
    for (;;) hlt();
}

/*
 * Shutdown using ACPI (via OSPM)
 */
void acpi_shutdown(void) {
    /* ACPI shutdown typically requires transitioning to S5 state */
    /* This is normally done via the FADT PM1 control registers */
    boot_printf("ACPI: System shutdown not fully implemented\n");
    boot_halt();
}

/*
 * Power off the system
 */
void acpi_power_off(void) {
    acpi_shutdown();
}