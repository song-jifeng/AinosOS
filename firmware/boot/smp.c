/*
 * AinosOS - boot/smp.c
 * Symmetric Multiprocessing (SMP) initialization
 *
 * Boots Application Processors (APs) from real mode to long mode
 * using the trampoline code defined in boot.S
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <arch/x86_64/registers.h>
#include <arch/x86_64/msr.h>

/* Maximum number of supported CPUs */
#define MAX_CPUS 64

/* AP trampoline location (must be in low memory < 1MB) */
#define AP_TRAMPOLINE_ADDR  0x7000

/* AP stack size */
#define AP_STACK_SIZE       8192

/* CPU state structure */
struct cpu_state {
    uint32_t apic_id;
    uint32_t cpu_number;
    uint64_t stack_base;
    uint64_t stack_top;
    uint64_t entry_point;
    volatile int started;
    volatile int online;
    char     name[16];
};

/* Per-CPU data */
static struct cpu_state cpus[MAX_CPUS];
static uint32_t cpu_count = 0;
static uint32_t bsp_apic_id = 0;

/* AP trampoline symbols (defined in boot.S) */
extern uint8_t ap_trampoline_start;
extern uint8_t ap_trampoline_end;
extern uint64_t ap_trampoline_pml4;
extern uint64_t ap_trampoline_stack;
extern uint64_t ap_trampoline_entry;

/* Synchronization for AP startup */
static volatile int ap_ready_count = 0;
static volatile int ap_start_barrier = 0;

/* AP initialization function pointer */
typedef void (*ap_init_func_t)(uint32_t cpu_number);
static ap_init_func_t ap_entry_func = NULL;

/*
 * AP startup entry point (called by each AP after entering long mode)
 */
static void ap_entry(uint32_t cpu_number) {
    struct cpu_state *state = &cpus[cpu_number];

    boot_printf("  AP %u (APIC ID %u) started\n", cpu_number, state->apic_id);

    state->online = 1;
    state->started = 1;

    /* Enable global interrupts */
    sti();

    /* Call the registered AP entry function */
    if (ap_entry_func) {
        ap_entry_func(cpu_number);
    }

    /* AP initialization complete - signal BSP */
    __sync_fetch_and_add(&ap_ready_count, 1);

    /* Halt until we have work to do */
    while (1) {
        hlt();
    }
}

/*
 * Initialize SMP: detect CPUs and boot APs
 */
void smp_init(void) {
    uint32_t eax, ebx, ecx, edx;

    boot_printf(BOOT_LOG_INIT "Initializing SMP...\n");

    /* Get BSP APIC ID */
    bsp_apic_id = apic_get_id();
    boot_printf("  BSP APIC ID: %u\n", bsp_apic_id);

    /* Set up BSP CPU state */
    cpus[0].apic_id     = bsp_apic_id;
    cpus[0].cpu_number  = 0;
    cpus[0].started     = 1;
    cpus[0].online      = 1;
    cpu_count = 1;

    /* Detect number of CPU cores via ACPI MADT */
    /* For now, check via CPUID for maximum core count */
    cpuid(1, &eax, &ebx, &ecx, &edx);
    uint32_t max_cores = 1;
    if (edx & (1 << 28)) {  /* HTT */
        max_cores = (ebx >> 16) & 0xFF;
        if (max_cores == 0) max_cores = 1;
    }

    /* Also try to use CPUID leaf 0x0B (Extended Topology) */
    if (cpu_max_leaf >= 0x0B) {
        cpuid_ex(0x0B, 0, &eax, &ebx, &ecx, &edx);
        if (ebx != 0) {
            max_cores = ecx & 0xFF;  /* Number of logical processors */
        }
    }

    /* Limit to MAX_CPUS */
    if (max_cores > MAX_CPUS) max_cores = MAX_CPUS;

    boot_printf("  Detected %u logical processors\n", max_cores);

    /* Copy the AP trampoline to low memory */
    smp_copy_trampoline();

    /* Boot each AP */
    for (uint32_t i = 1; i < max_cores; i++) {
        smp_boot_ap(i);
    }

    boot_printf(BOOT_LOG_OK "SMP: %u CPUs online\n", cpu_count);
}

/*
 * Copy the AP trampoline code to low memory (< 1MB)
 */
void smp_copy_trampoline(void) {
    uint8_t *src = (uint8_t*)&ap_trampoline_start;
    uint8_t *dst = (uint8_t*)(uint64_t)AP_TRAMPOLINE_ADDR;
    uint32_t size = (uint32_t)((uint64_t)&ap_trampoline_end - (uint64_t)&ap_trampoline_start);

    boot_printf("  Copying AP trampoline to 0x%X (%u bytes)\n", AP_TRAMPOLINE_ADDR, size);

    /* Copy the trampoline code */
    for (uint32_t i = 0; i < size; i++) {
        dst[i] = src[i];
    }

    /* Flush caches to ensure AP sees the code */
    __sync_synchronize();
}

/*
 * Boot an Application Processor
 *
 * The boot sequence:
 *   1. Send INIT IPI to the AP
 *   2. Wait for 10ms
 *   3. Send STARTUP IPI with trampoline address
 *   4. Wait for 10ms
 *   5. Send a second STARTUP IPI (required by spec)
 *   6. Wait for AP to signal readiness
 */
void smp_boot_ap(uint32_t cpu_number) {
    struct cpu_state *state = &cpus[cpu_number];
    uint32_t apic_id = cpu_number;  /* Default: APIC ID = CPU number */

    boot_printf("  Booting AP %u...\n", cpu_number);

    /* Allocate stack for this AP */
    state->stack_base = (uint64_t)boot_alloc(AP_STACK_SIZE);
    if (!state->stack_base) {
        boot_printf(BOOT_LOG_FAIL "  Failed to allocate stack for AP %u\n", cpu_number);
        return;
    }
    state->stack_top = state->stack_base + AP_STACK_SIZE - 16;
    state->entry_point = (uint64_t)&ap_entry;
    state->cpu_number = cpu_number;
    state->started = 0;
    state->online = 0;

    /* Set up trampoline variables */
    ap_trampoline_pml4   = (uint64_t)&pml4;
    ap_trampoline_stack  = state->stack_top;
    ap_trampoline_entry  = state->entry_point;

    /* Ensure trampoline variables are visible to AP */
    __sync_synchronize();

    /* Send INIT IPI */
    boot_printf("    Sending INIT IPI to APIC %u...\n", apic_id);
    apic_send_init_ipi(apic_id);

    /* Wait 10ms (INIT IPI requires a delay) */
    smp_mdelay(10);

    /* Send first STARTUP IPI */
    boot_printf("    Sending STARTUP IPI #1...\n");
    apic_send_startup_ipi(apic_id, AP_TRAMPOLINE_ADDR >> 12);

    /* Wait 10ms */
    smp_mdelay(10);

    /* Send second STARTUP IPI (required by Intel MP spec) */
    boot_printf("    Sending STARTUP IPI #2...\n");
    apic_send_startup_ipi(apic_id, AP_TRAMPOLINE_ADDR >> 12);

    /* Wait for AP to start (up to 1 second) */
    uint64_t timeout = 1000000;  /* ~1 second */
    while (timeout > 0 && !state->started) {
        smp_udelay(1);
        timeout--;
    }

    if (state->started) {
        boot_printf("    AP %u started successfully\n", cpu_number);
        cpu_count++;
    } else {
        boot_printf(BOOT_LOG_FAIL "    AP %u failed to start\n", cpu_number);
    }
}

/*
 * Register an AP entry function
 */
void smp_register_ap_entry(ap_init_func_t func) {
    ap_entry_func = func;
}

/*
 * Wait for all APs to finish initialization
 */
void smp_wait_for_aps(void) {
    /* Wait for all APs to signal ready */
    while (ap_ready_count < cpu_count - 1) {
        __asm__ volatile("pause");
    }
}

/*
 * Get the number of online CPUs
 */
uint32_t smp_get_cpu_count(void) {
    return cpu_count;
}

/*
 * Get CPU state for a specific CPU
 */
struct cpu_state *smp_get_cpu_state(uint32_t cpu_number) {
    if (cpu_number < cpu_count) {
        return &cpus[cpu_number];
    }
    return NULL;
}

/*
 * Get the current CPU's number (uses GS segment base)
 */
uint32_t smp_get_current_cpu(void) {
    /* Read the current CPU number from GS base */
    uint64_t gs_base = read_gs_base();
    return (uint32_t)(gs_base & 0xFFFFFFFF);
}

/*
 * Set up per-CPU data area (using GS segment)
 */
void smp_setup_per_cpu(uint32_t cpu_number) {
    /* Allocate per-CPU data */
    struct cpu_state *state = &cpus[cpu_number];
    write_gs_base((uint64_t)state);
}

/*
 * Microsecond delay (busy-loop using I/O port)
 */
void smp_udelay(uint32_t us) {
    /* Approximate delay using PIT or simple loop */
    for (volatile uint32_t i = 0; i < us * 4; i++) {
        __asm__ volatile("pause");
    }
}

/*
 * Millisecond delay
 */
void smp_mdelay(uint32_t ms) {
    for (uint32_t i = 0; i < ms; i++) {
        smp_udelay(1000);
    }
}

/*
 * Wake up all APs (for broadcast operations)
 */
void smp_wake_all_aps(void) {
    apic_send_broadcast_ipi(0x20);  /* IPI vector 0x20 */
}

/*
 * Check if a specific CPU is online
 */
int smp_is_cpu_online(uint32_t cpu_number) {
    if (cpu_number < cpu_count) {
        return cpus[cpu_number].online;
    }
    return 0;
}

/*
 * Synchronization barrier for all CPUs
 */
void smp_barrier(void) {
    /* Simple barrier using atomic increment */
    static volatile int barrier_count = 0;
    int target = cpu_count;

    __sync_fetch_and_add(&barrier_count, 1);
    while (barrier_count < target) {
        __asm__ volatile("pause");
    }
    __sync_synchronize();
}

/*
 * Read the APIC ID of a specific CPU
 */
uint32_t smp_get_apic_id(uint32_t cpu_number) {
    if (cpu_number < cpu_count) {
        return cpus[cpu_number].apic_id;
    }
    return 0xFFFFFFFF;
}