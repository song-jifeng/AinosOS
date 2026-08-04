/*
 * AinosOS - boot/apic.c
 * Local APIC (LAPIC) and I/O APIC initialization
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <arch/x86_64/registers.h>
#include <arch/x86_64/msr.h>

/* LAPIC MMIO registers (xAPIC mode) */
#define LAPIC_REG_ID            0x020
#define LAPIC_REG_VERSION       0x030
#define LAPIC_REG_TPR           0x080
#define LAPIC_REG_APR           0x090
#define LAPIC_REG_PPR           0x0A0
#define LAPIC_REG_EOI           0x0B0
#define LAPIC_REG_RRD           0x0C0
#define LAPIC_REG_LDR           0x0D0
#define LAPIC_REG_DFR           0x0E0
#define LAPIC_REG_SVR           0x0F0
#define LAPIC_REG_ISR_BASE      0x100
#define LAPIC_REG_TMR_BASE      0x180
#define LAPIC_REG_IRR_BASE      0x200
#define LAPIC_REG_ESR           0x280
#define LAPIC_REG_ICR_LOW       0x300
#define LAPIC_REG_ICR_HIGH      0x310
#define LAPIC_REG_LVT_TIMER     0x320
#define LAPIC_REG_LVT_THERMAL   0x330
#define LAPIC_REG_LVT_PERFMON   0x340
#define LAPIC_REG_LVT_LINT0     0x350
#define LAPIC_REG_LVT_LINT1     0x360
#define LAPIC_REG_LVT_ERROR     0x370
#define LAPIC_REG_INIT_COUNT    0x380
#define LAPIC_REG_CUR_COUNT     0x390
#define LAPIC_REG_DIV_CONF      0x3E0

/* LAPIC flags */
#define LAPIC_SVR_ENABLE        (1 << 8)
#define LAPIC_SVR_FOCUS         (1 << 9)
#define LAPIC_SVR_SPURIOUS_VEC  0xFF
#define LAPIC_LVT_MASKED        (1 << 16)
#define LAPIC_LVT_TRIGGER_LEVEL (1 << 13)
#define LAPIC_LVT_REMOTE_IRR    (1 << 14)
#define LAPIC_LVT_DELIVERY_FIXED  0
#define LAPIC_LVT_DELIVERY_SMI    (1 << 8)
#define LAPIC_LVT_DELIVERY_NMI    (4 << 8)
#define LAPIC_LVT_DELIVERY_INIT   (5 << 8)
#define LAPIC_LVT_DELIVERY_EXTINT (7 << 8)
#define LAPIC_LVT_TIMER_ONESHOT   0
#define LAPIC_LVT_TIMER_PERIODIC  (1 << 17)
#define LAPIC_LVT_TIMER_TSCDEADLINE (2 << 17)
#define LAPIC_ICR_INIT           (5 << 8)
#define LAPIC_ICR_STARTUP        (6 << 8)
#define LAPIC_ICR_LEVEL          (1 << 14)
#define LAPIC_ICR_ASSERT         (1 << 14)
#define LAPIC_ICR_DEASSERT       (0 << 14)
#define LAPIC_ICR_TRIGGER_LEVEL  (1 << 15)
#define LAPIC_ICR_ALL_EXCLUDING_SELF (3 << 18)
#define LAPIC_ICR_DEST_FIELD     0xFF000000
#define LAPIC_ICR_DELIVERY_PENDING (1 << 12)

/* I/O APIC registers */
#define IOAPIC_REG_IOREGSEL     0x00
#define IOAPIC_REG_IOWIN        0x10
#define IOAPIC_REG_ID           0x00
#define IOAPIC_REG_VERSION      0x01
#define IOAPIC_REG_ARB          0x02
#define IOAPIC_REDIR_TBL_BASE   0x10

/* I/O APIC redirection entry bits */
#define IOAPIC_REDIR_MASKED     (1 << 16)
#define IOAPIC_REDIR_PHYSICAL   0
#define IOAPIC_REDIR_LOGICAL    (1 << 11)
#define IOAPIC_REDIR_LEVEL      (1 << 15)
#define IOAPIC_REDIR_REMOTE_IRR (1 << 14)
#define IOAPIC_REDIR_LOW_POLARITY (1 << 13)

/* LAPIC base address */
static uint64_t lapic_base = 0;
static int x2apic_enabled = 0;

/* LAPIC MMIO base pointer */
static volatile uint32_t *lapic_mmio = NULL;

/* I/O APIC base address */
static uint64_t ioapic_base = 0;
static uint32_t ioapic_id = 0;
static uint32_t ioapic_version = 0;
static uint32_t ioapic_max_redir = 0;

/*
 * MMIO read/write helpers for LAPIC
 */
static inline uint32_t lapic_read(uint32_t reg) {
    return *(volatile uint32_t*)((uint64_t)lapic_mmio + reg);
}

static inline void lapic_write(uint32_t reg, uint32_t val) {
    *(volatile uint32_t*)((uint64_t)lapic_mmio + reg) = val;
}

/*
 * I/O APIC MMIO access
 */
static inline uint32_t ioapic_read(uint32_t reg) {
    *(volatile uint32_t*)(uint64_t)ioapic_base = reg;
    return *(volatile uint32_t*)((uint64_t)ioapic_base + IOAPIC_REG_IOWIN);
}

static inline void ioapic_write(uint32_t reg, uint32_t val) {
    *(volatile uint32_t*)(uint64_t)ioapic_base = reg;
    *(volatile uint32_t*)((uint64_t)ioapic_base + IOAPIC_REG_IOWIN) = val;
}

/*
 * Initialize the Local APIC
 */
void apic_init(void) {
    uint64_t apic_base_msr;

    boot_printf(BOOT_LOG_INIT "Initializing APIC...\n");

    /* Read APIC base MSR */
    apic_base_msr = read_msr(MSR_IA32_APIC_BASE);

    /* Check if APIC is enabled */
    if (!(apic_base_msr & APIC_BASE_ENABLE)) {
        boot_printf(BOOT_LOG_WARN "APIC not enabled by BIOS, enabling...\n");
        apic_base_msr |= APIC_BASE_ENABLE;
        write_msr(MSR_IA32_APIC_BASE, apic_base_msr);
    }

    /* Check for x2APIC support */
    if (boot_cpu_has_feature(21, 1)) {  /* x2APIC feature */
        boot_printf("  x2APIC supported\n");
        /* Enable x2APIC */
        apic_base_msr |= APIC_BASE_X2APIC;
        write_msr(MSR_IA32_APIC_BASE, apic_base_msr);
        x2apic_enabled = 1;
        boot_printf(BOOT_LOG_OK "x2APIC mode enabled\n");
    } else {
        /* Get LAPIC base address */
        lapic_base = apic_base_msr & APIC_BASE_PHYS_ADDR_MASK;
        lapic_mmio = (volatile uint32_t*)(uint64_t)lapic_base;

        boot_printf("  LAPIC base: 0x%016llX\n", lapic_base);
        boot_printf(BOOT_LOG_OK "xAPIC mode enabled\n");
    }

    /* Get LAPIC version */
    if (x2apic_enabled) {
        uint32_t version = (uint32_t)read_msr(MSR_IA32_X2APIC_VERSION);
        boot_printf("  LAPIC version: 0x%08X\n", version);
    } else {
        uint32_t version = lapic_read(LAPIC_REG_VERSION);
        boot_printf("  LAPIC version: 0x%08X\n", version);
    }

    /* Enable the LAPIC */
    if (x2apic_enabled) {
        uint64_t svr = read_msr(MSR_IA32_X2APIC_SVR);
        svr = (svr & ~0xFF) | LAPIC_SVR_ENABLE | 0xFF;  /* Spurious vector = 0xFF */
        write_msr(MSR_IA32_X2APIC_SVR, svr);
    } else {
        uint32_t svr = lapic_read(LAPIC_REG_SVR);
        svr = (svr & ~0xFF) | LAPIC_SVR_ENABLE | 0xFF;
        lapic_write(LAPIC_REG_SVR, svr);
    }

    /* Mask all LVT entries */
    apic_mask_all_lvts();

    boot_printf(BOOT_LOG_OK "APIC initialized\n");
}

/*
 * Get the LAPIC ID
 */
uint32_t apic_get_id(void) {
    if (x2apic_enabled) {
        return (uint32_t)read_msr(MSR_IA32_X2APIC_APICID);
    } else {
        return lapic_read(LAPIC_REG_ID) >> 24;
    }
}

/*
 * Get the LAPIC version
 */
uint32_t apic_get_version(void) {
    if (x2apic_enabled) {
        return (uint32_t)read_msr(MSR_IA32_X2APIC_VERSION);
    } else {
        return lapic_read(LAPIC_REG_VERSION);
    }
}

/*
 * Send EOI (End of Interrupt) to LAPIC
 */
void apic_send_eoi(void) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_EOI, 0);
    } else {
        lapic_write(LAPIC_REG_EOI, 0);
    }
}

/*
 * Read the LAPIC TPR (Task Priority Register)
 */
uint32_t apic_get_tpr(void) {
    if (x2apic_enabled) {
        return (uint32_t)read_msr(MSR_IA32_X2APIC_TPR);
    } else {
        return lapic_read(LAPIC_REG_TPR);
    }
}

/*
 * Set the LAPIC TPR
 */
void apic_set_tpr(uint32_t tpr) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_TPR, tpr);
    } else {
        lapic_write(LAPIC_REG_TPR, tpr);
    }
}

/*
 * Mask all LVT (Local Vector Table) entries
 */
void apic_mask_all_lvts(void) {
    uint32_t mask = LAPIC_LVT_MASKED;

    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_LVT_TIMER,   mask);
        write_msr(MSR_IA32_X2APIC_LVT_PMI,     mask);
        write_msr(MSR_IA32_X2APIC_LVT_LINT0,   mask);
        write_msr(MSR_IA32_X2APIC_LVT_LINT1,   mask);
        write_msr(MSR_IA32_X2APIC_LVT_ERROR,   mask);
    } else {
        lapic_write(LAPIC_REG_LVT_TIMER,   mask);
        lapic_write(LAPIC_REG_LVT_THERMAL, mask);
        lapic_write(LAPIC_REG_LVT_PERFMON, mask);
        lapic_write(LAPIC_REG_LVT_LINT0,   mask);
        lapic_write(LAPIC_REG_LVT_LINT1,   mask);
        lapic_write(LAPIC_REG_LVT_ERROR,   mask);
    }
}

/*
 * Configure LVT LINT0 (typically used for PIC mode)
 */
void apic_set_lint0(uint32_t flags) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_LVT_LINT0, flags);
    } else {
        lapic_write(LAPIC_REG_LVT_LINT0, flags);
    }
}

/*
 * Configure LVT LINT1 (typically used for NMI)
 */
void apic_set_lint1(uint32_t flags) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_LVT_LINT1, flags);
    } else {
        lapic_write(LAPIC_REG_LVT_LINT1, flags);
    }
}

/*
 * Configure LVT Timer
 */
void apic_set_timer_vector(uint32_t vector, uint32_t flags) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_LVT_TIMER, vector | flags);
    } else {
        lapic_write(LAPIC_REG_LVT_TIMER, vector | flags);
    }
}

/*
 * Initialize the LAPIC timer
 * Calibrate against a known time source and set up periodic interrupts
 */
void apic_timer_init(uint32_t vector, uint32_t frequency_hz) {
    uint32_t init_count;

    boot_printf(BOOT_LOG_INIT "Initializing APIC timer...\n");

    /* Divide configuration: divide by 16 */
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_DIV_CONF, 0x03);  /* Divide by 16 */
    } else {
        lapic_write(LAPIC_REG_DIV_CONF, 0x03);
    }

    /* Calibrate: use PIT to measure LAPIC timer ticks */
    /* First, set up PIT timer */
    outb(0x43, 0x34);  /* Channel 0, lobyte/hibyte, rate generator */
    outb(0x40, 0xFF);  /* Maximum count */
    outb(0x40, 0xFF);

    /* LAPIC: set maximum initial count and start counting */
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_INIT_COUNT, 0xFFFFFFFF);
    } else {
        lapic_write(LAPIC_REG_INIT_COUNT, 0xFFFFFFFF);
    }

    /* Wait for PIT to count down (about 54ms with max count) */
    uint32_t pit_count;
    do {
        outb(0x43, 0x00);  /* Latch counter 0 */
        pit_count = inb(0x40);
        pit_count |= inb(0x40) << 8;
    } while (pit_count > 0x100);  /* Wait for ~54ms */

    /* Stop LAPIC timer */
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_INIT_COUNT, 0);
    } else {
        lapic_write(LAPIC_REG_INIT_COUNT, 0);
    }

    /* Read current count */
    uint32_t current_count;
    if (x2apic_enabled) {
        current_count = (uint32_t)read_msr(MSR_IA32_X2APIC_CUR_COUNT);
    } else {
        current_count = lapic_read(LAPIC_REG_CUR_COUNT);
    }

    /* Calculate bus frequency */
    uint32_t elapsed = 0xFFFFFFFF - current_count;
    uint32_t bus_freq = elapsed * 1193182 / 0xFFFF;  /* PIT runs at 1.193182 MHz */

    boot_printf("  APIC bus frequency: %u Hz\n", bus_freq);

    /* Set up periodic timer */
    if (frequency_hz > 0) {
        init_count = bus_freq / frequency_hz;
    } else {
        init_count = bus_freq / 100;  /* Default: 100 Hz */
    }

    /* Set timer vector and periodic mode */
    apic_set_timer_vector(vector, LAPIC_LVT_TIMER_PERIODIC);

    /* Set initial count */
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_DIV_CONF, 0x03);  /* Divide by 16 */
        write_msr(MSR_IA32_X2APIC_INIT_COUNT, init_count / 16);
    } else {
        lapic_write(LAPIC_REG_DIV_CONF, 0x03);
        lapic_write(LAPIC_REG_INIT_COUNT, init_count / 16);
    }

    boot_printf(BOOT_LOG_OK "APIC timer initialized at %u Hz\n", frequency_hz ? frequency_hz : 100);
}

/*
 * Send INIT IPI to a target APIC ID
 */
void apic_send_init_ipi(uint32_t apic_id) {
    if (x2apic_enabled) {
        uint64_t icr = (uint64_t)apic_id << 32;
        icr |= LAPIC_ICR_INIT | LAPIC_ICR_LEVEL | LAPIC_ICR_ASSERT;
        write_msr(MSR_IA32_X2APIC_ICR, icr);
    } else {
        lapic_write(LAPIC_REG_ICR_HIGH, apic_id << 24);
        lapic_write(LAPIC_REG_ICR_LOW,  LAPIC_ICR_INIT | LAPIC_ICR_LEVEL | LAPIC_ICR_ASSERT);
    }

    /* Wait for delivery to complete */
    apic_wait_for_icr_idle();
}

/*
 * Send STARTUP IPI to a target APIC ID
 */
void apic_send_startup_ipi(uint32_t apic_id, uint32_t vector) {
    if (x2apic_enabled) {
        uint64_t icr = (uint64_t)apic_id << 32;
        icr |= LAPIC_ICR_STARTUP | vector;
        write_msr(MSR_IA32_X2APIC_ICR, icr);
    } else {
        lapic_write(LAPIC_REG_ICR_HIGH, apic_id << 24);
        lapic_write(LAPIC_REG_ICR_LOW,  LAPIC_ICR_STARTUP | vector);
    }

    /* Wait for delivery to complete */
    apic_wait_for_icr_idle();
}

/*
 * Wait for ICR to become idle
 */
void apic_wait_for_icr_idle(void) {
    if (x2apic_enabled) {
        /* x2APIC write is serialized, just a small delay */
        for (volatile int i = 0; i < 10; i++) {
            __asm__ volatile("pause");
        }
    } else {
        /* Wait for delivery status bit to clear */
        while (lapic_read(LAPIC_REG_ICR_LOW) & LAPIC_ICR_DELIVERY_PENDING) {
            __asm__ volatile("pause");
        }
    }
}

/*
 * Send a fixed IPI to a target APIC ID
 */
void apic_send_ipi(uint32_t apic_id, uint32_t vector) {
    if (x2apic_enabled) {
        uint64_t icr = (uint64_t)apic_id << 32;
        icr |= vector;
        write_msr(MSR_IA32_X2APIC_ICR, icr);
    } else {
        lapic_write(LAPIC_REG_ICR_HIGH, apic_id << 24);
        lapic_write(LAPIC_REG_ICR_LOW,  vector);
    }
    apic_wait_for_icr_idle();
}

/*
 * Send broadcast IPI (all except self)
 */
void apic_send_broadcast_ipi(uint32_t vector) {
    if (x2apic_enabled) {
        write_msr(MSR_IA32_X2APIC_ICR,
                  LAPIC_ICR_ALL_EXCLUDING_SELF | vector);
    } else {
        lapic_write(LAPIC_REG_ICR_HIGH, 0);
        lapic_write(LAPIC_REG_ICR_LOW, LAPIC_ICR_ALL_EXCLUDING_SELF | vector);
    }
    apic_wait_for_icr_idle();
}

/*
 * Initialize I/O APIC
 */
void ioapic_init(uint64_t ioapic_base_addr) {
    ioapic_base = ioapic_base_addr;

    boot_printf(BOOT_LOG_INIT "Initializing I/O APIC at 0x%016llX...\n", ioapic_base);

    /* Read I/O APIC ID */
    ioapic_write(IOAPIC_REG_IOREGSEL, IOAPIC_REG_ID);
    ioapic_id = ioapic_read(IOAPIC_REG_IOWIN) >> 24;

    /* Read I/O APIC version */
    ioapic_write(IOAPIC_REG_IOREGSEL, IOAPIC_REG_VERSION);
    ioapic_version = ioapic_read(IOAPIC_REG_IOWIN) & 0xFF;
    ioapic_max_redir = (ioapic_read(IOAPIC_REG_IOWIN) >> 16) & 0xFF;

    boot_printf(BOOT_LOG_OK "I/O APIC: ID=%u, Version=%u, Max Redir=%u\n",
                ioapic_id, ioapic_version, ioapic_max_redir);

    /* Mask all I/O APIC redirection entries */
    ioapic_mask_all();
}

/*
 * Mask all I/O APIC redirection entries
 */
void ioapic_mask_all(void) {
    for (uint32_t i = 0; i <= ioapic_max_redir; i++) {
        ioapic_set_redirection(i, IOAPIC_REDIR_MASKED, 0, 0);
    }
}

/*
 * Configure an I/O APIC redirection entry
 */
void ioapic_set_redirection(uint32_t index, uint32_t flags,
                             uint32_t vector, uint32_t dest) {
    uint32_t reg = IOAPIC_REDIR_TBL_BASE + index * 2;

    /* Low 32 bits: vector and flags */
    ioapic_write(IOAPIC_REG_IOREGSEL, reg);
    ioapic_write(IOAPIC_REG_IOWIN, vector | flags);

    /* High 32 bits: destination APIC ID */
    ioapic_write(IOAPIC_REG_IOREGSEL, reg + 1);
    ioapic_write(IOAPIC_REG_IOWIN, dest << 24);
}

/*
 * Route an IRQ through the I/O APIC
 */
void ioapic_route_irq(uint32_t irq, uint32_t vector, uint32_t apic_id) {
    ioapic_set_redirection(irq, 0, vector, apic_id);
}

/*
 * Get the I/O APIC base address
 */
uint64_t ioapic_get_base(void) {
    return ioapic_base;
}

/*
 * Check if I/O APIC is initialized
 */
int ioapic_is_initialized(void) {
    return ioapic_base != 0;
}