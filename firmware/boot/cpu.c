/*
 * AinosOS - boot/cpu.c
 * CPU detection and feature enumeration using CPUID
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <arch/x86_64/registers.h>

/* CPU vendor strings */
static char cpu_vendor[13] = {0};
static char cpu_brand[49] = {0};

/* CPU feature sets */
static uint32_t cpu_features_1_edx = 0;  /* CPUID leaf 1, EDX */
static uint32_t cpu_features_1_ecx = 0;  /* CPUID leaf 1, ECX */
static uint32_t cpu_features_ext_edx = 0; /* CPUID leaf 0x80000001, EDX */
static uint32_t cpu_features_ext_ecx = 0; /* CPUID leaf 0x80000001, ECX */
static uint32_t cpu_features_7_ebx = 0;   /* CPUID leaf 7, EBX */
static uint32_t cpu_features_7_ecx = 0;   /* CPUID leaf 7, ECX */

/* CPU info */
static uint32_t cpu_family = 0;
static uint32_t cpu_model = 0;
static uint32_t cpu_stepping = 0;
static uint32_t cpu_max_leaf = 0;
static uint32_t cpu_max_ext_leaf = 0;
static uint32_t cpu_cores = 1;
static uint32_t cpu_threads = 1;
static uint32_t cpu_apic_id = 0;

/* Cache info */
static uint32_t l1_cache_size = 0;
static uint32_t l2_cache_size = 0;
static uint32_t l3_cache_size = 0;

/*
 * CPU feature name table
 */
struct cpu_feature {
    uint32_t bit;
    uint32_t reg;  /* 0=EDX, 1=ECX, 2=extEDX, 3=extECX, 4=7EBX, 5=7ECX */
    const char *name;
};

static const struct cpu_feature cpu_feature_table[] = {
    /* CPUID leaf 1, EDX */
    { 0,  0, "FPU (x87 FPU)" },
    { 1,  0, "VME (Virtual 8086 Mode Extensions)" },
    { 2,  0, "DE (Debugging Extensions)" },
    { 3,  0, "PSE (Page Size Extension)" },
    { 4,  0, "TSC (Time Stamp Counter)" },
    { 5,  0, "MSR (Model-Specific Registers)" },
    { 6,  0, "PAE (Physical Address Extension)" },
    { 7,  0, "MCE (Machine Check Exception)" },
    { 8,  0, "CX8 (CMPXCHG8B)" },
    { 9,  0, "APIC (On-chip APIC)" },
    { 11, 0, "SEP (SYSENTER/SYSEXIT)" },
    { 12, 0, "MTRR (Memory Type Range Registers)" },
    { 13, 0, "PGE (Page Global Enable)" },
    { 14, 0, "MCA (Machine Check Architecture)" },
    { 15, 0, "CMOV (Conditional Move)" },
    { 16, 0, "PAT (Page Attribute Table)" },
    { 17, 0, "PSE-36 (36-bit Page Size Extension)" },
    { 18, 0, "PSN (Processor Serial Number)" },
    { 19, 0, "CLFSH (CLFLUSH)" },
    { 21, 0, "DS (Debug Store)" },
    { 22, 0, "ACPI (ACPI via MSR)" },
    { 23, 0, "MMX (MMX Technology)" },
    { 24, 0, "FXSR (FXSAVE/FXRSTOR)" },
    { 25, 0, "SSE (SSE)" },
    { 26, 0, "SSE2 (SSE2)" },
    { 27, 0, "SS (Self Snoop)" },
    { 28, 0, "HTT (Hyper-Threading Technology)" },
    { 29, 0, "TM (Thermal Monitor)" },
    { 30, 0, "IA64 (IA-64)" },
    { 31, 0, "PBE (Pending Break Enable)" },

    /* CPUID leaf 1, ECX */
    { 0,  1, "SSE3 (SSE3)" },
    { 1,  1, "PCLMULQDQ (PCLMULQDQ)" },
    { 2,  1, "DTES64 (64-bit DS Area)" },
    { 3,  1, "MONITOR (MONITOR/MWAIT)" },
    { 4,  1, "DS-CPL (CPL-qualified DS)" },
    { 5,  1, "VMX (Virtual Machine Extensions)" },
    { 6,  1, "SMX (Safer Mode Extensions)" },
    { 7,  1, "EST (Enhanced SpeedStep)" },
    { 8,  1, "TM2 (Thermal Monitor 2)" },
    { 9,  1, "SSSE3 (Supplemental SSE3)" },
    { 10, 1, "CNXT-ID (L1 Context ID)" },
    { 11, 1, "SDBG (Silicon Debug)" },
    { 12, 1, "FMA (Fused Multiply-Add)" },
    { 13, 1, "CX16 (CMPXCHG16B)" },
    { 14, 1, "xTPR (xTPR Update Control)" },
    { 15, 1, "PDCM (Perf/Debug Capability)" },
    { 17, 1, "PCID (Process Context ID)" },
    { 18, 1, "DCA (Direct Cache Access)" },
    { 19, 1, "SSE4.1 (SSE4.1)" },
    { 20, 1, "SSE4.2 (SSE4.2)" },
    { 21, 1, "x2APIC (x2APIC)" },
    { 22, 1, "MOVBE (MOVBE)" },
    { 23, 1, "POPCNT (POPCNT)" },
    { 24, 1, "TSC-Deadline (TSC Deadline)" },
    { 25, 1, "AES (AES)" },
    { 26, 1, "XSAVE (XSAVE)" },
    { 27, 1, "OSXSAVE (OSXSAVE)" },
    { 28, 1, "AVX (AVX)" },
    { 29, 1, "F16C (Half-Precision)" },
    { 30, 1, "RDRAND (RDRAND)" },
    { 31, 1, "HYPERVISOR (Hypervisor)" },

    /* Extended features (0x80000001), EDX */
    { 11, 2, "SYSCALL (SYSCALL/SYSRET)" },
    { 20, 2, "NX (No-Execute Page)" },
    { 22, 2, "MMXEXT (MMX Extensions)" },
    { 25, 2, "FFXSR (Fast FXSAVE/FXRSTOR)" },
    { 26, 2, "1GBPage (1GiB Pages)" },
    { 27, 2, "RDTSCP (RDTSCP)" },
    { 29, 2, "LM (Long Mode)" },
    { 30, 2, "3DNowExt (3DNow! Extensions)" },
    { 31, 2, "3DNow (3DNow!)" },
};

/*
 * Detect CPU vendor string
 */
static void cpu_detect_vendor(void) {
    uint32_t eax, ebx, ecx, edx;
    cpuid(0, &eax, &ebx, &ecx, &edx);

    cpu_max_leaf = eax;
    *(uint32_t*)&cpu_vendor[0] = ebx;
    *(uint32_t*)&cpu_vendor[4] = edx;
    *(uint32_t*)&cpu_vendor[8] = ecx;
    cpu_vendor[12] = '\0';
}

/*
 * Detect CPU brand string (using extended leaves)
 */
static void cpu_detect_brand(void) {
    if (cpu_max_ext_leaf < 0x80000004) {
        return;
    }

    uint32_t *brand = (uint32_t*)cpu_brand;
    for (uint32_t leaf = 0x80000002; leaf <= 0x80000004; leaf++) {
        uint32_t eax, ebx, ecx, edx;
        cpuid(leaf, &eax, &ebx, &ecx, &edx);
        *brand++ = eax;
        *brand++ = ebx;
        *brand++ = ecx;
        *brand++ = edx;
    }
    cpu_brand[48] = '\0';
}

/*
 * Detect CPU family, model, stepping
 */
static void cpu_detect_family_model(void) {
    uint32_t eax, ebx, ecx, edx;
    cpuid(1, &eax, &ebx, &ecx, &edx);

    cpu_stepping = eax & 0x0F;
    cpu_model = (eax >> 4) & 0x0F;
    cpu_family = (eax >> 8) & 0x0F;

    /* Extended model and family */
    if (cpu_family == 0x0F) {
        cpu_family += (eax >> 20) & 0xFF;
    }
    if (cpu_family == 0x0F || cpu_family == 0x06) {
        cpu_model += ((eax >> 16) & 0x0F) << 4;
    }

    /* Get APIC ID */
    cpu_apic_id = (ebx >> 24) & 0xFF;

    /* Get thread/core counts */
    uint8_t htt = (edx >> 28) & 1;
    if (htt) {
        cpu_threads = (ebx >> 16) & 0xFF;
    }

    /* Save feature flags */
    cpu_features_1_edx = edx;
    cpu_features_1_ecx = ecx;
}

/*
 * Detect extended features
 */
static void cpu_detect_extended(void) {
    uint32_t eax, ebx, ecx, edx;

    /* Get max extended leaf */
    cpuid(0x80000000, &eax, &ebx, &ecx, &edx);
    cpu_max_ext_leaf = eax;

    if (cpu_max_ext_leaf >= 0x80000001) {
        cpuid(0x80000001, &eax, &ebx, &ecx, &edx);
        cpu_features_ext_edx = edx;
        cpu_features_ext_ecx = ecx;
    }

    if (cpu_max_ext_leaf >= 0x80000008) {
        cpuid(0x80000008, &eax, &ebx, &ecx, &edx);
        /* Physical address width in EAX bits 0-7 */
        /* Linear address width in EAX bits 8-15 */
    }
}

/*
 * Detect structured extended features (leaf 7)
 */
static void cpu_detect_extended_features(void) {
    uint32_t eax, ebx, ecx, edx;

    if (cpu_max_leaf >= 7) {
        cpuid_ex(7, 0, &eax, &ebx, &ecx, &edx);
        cpu_features_7_ebx = ebx;
        cpu_features_7_ecx = ecx;
    }
}

/*
 * Detect cache information
 */
static void cpu_detect_cache(void) {
    uint32_t eax, ebx, ecx, edx;

    if (cpu_max_leaf >= 4) {
        /* Intel-style cache info using CPUID leaf 4 */
        for (int cache_type = 0; cache_type < 3; cache_type++) {
            cpuid_ex(4, cache_type, &eax, &ebx, &ecx, &edx);
            uint32_t type = eax & 0x1F;
            if (type == 0) break;  /* No more caches */

            uint32_t ways = ((ebx >> 22) & 0x3FF) + 1;
            uint32_t partitions = ((ebx >> 12) & 0x3FF) + 1;
            uint32_t line_size = (ebx & 0xFFF) + 1;
            uint32_t sets = ecx + 1;
            uint32_t size = ways * partitions * line_size * sets;

            switch (type) {
                case 1: l1_cache_size = size; break;  /* Data cache */
                case 2: l1_cache_size = size; break;  /* Instruction cache */
                case 3: l2_cache_size = size; break;  /* Unified cache */
                case 4: l3_cache_size = size; break;  /* Unified cache */
            }
        }
    }
}

/*
 * Perform CPU detection
 */
void boot_detect_cpu(void) {
    boot_printf(BOOT_LOG_INIT "Detecting CPU...\n");

    cpu_detect_vendor();
    cpu_detect_family_model();
    cpu_detect_extended();
    cpu_detect_extended_features();
    cpu_detect_brand();
    cpu_detect_cache();

    boot_printf(BOOT_LOG_OK "CPU: %s\n", cpu_vendor);
    if (cpu_brand[0]) {
        boot_printf("  Model: %s\n", cpu_brand);
    }
    boot_printf("  Family: %u, Model: %u, Stepping: %u\n",
                cpu_family, cpu_model, cpu_stepping);
    boot_printf("  Cores: %u, Threads: %u, APIC ID: %u\n",
                cpu_cores, cpu_threads, cpu_apic_id);
    boot_printf("  Cache: L1=%uK, L2=%uK, L3=%uK\n",
                l1_cache_size / 1024, l2_cache_size / 1024, l3_cache_size / 1024);
}

/*
 * Get CPU vendor string
 */
const char *boot_get_cpu_vendor(void) {
    return cpu_vendor;
}

/*
 * Get CPU brand string
 */
const char *boot_get_cpu_brand(void) {
    return cpu_brand;
}

/*
 * Get CPU feature flags (EDX from leaf 1)
 */
uint32_t boot_get_cpu_features(void) {
    return cpu_features_1_edx;
}

/*
 * Get CPU extended feature flags (ECX from leaf 1)
 */
uint32_t boot_get_cpu_ext_features(void) {
    return cpu_features_1_ecx;
}

/*
 * Get extended features (EDX from leaf 0x80000001)
 */
uint32_t boot_get_cpu_ext_features2(void) {
    return cpu_features_ext_edx;
}

/*
 * Check if a specific feature is supported
 */
int boot_cpu_has_feature(uint32_t bit, uint32_t reg) {
    switch (reg) {
        case 0: return (cpu_features_1_edx >> bit) & 1;
        case 1: return (cpu_features_1_ecx >> bit) & 1;
        case 2: return (cpu_features_ext_edx >> bit) & 1;
        case 3: return (cpu_features_ext_ecx >> bit) & 1;
        case 4: return (cpu_features_7_ebx >> bit) & 1;
        case 5: return (cpu_features_7_ecx >> bit) & 1;
        default: return 0;
    }
}

/*
 * Print all supported CPU features
 */
void boot_cpu_print_features(void) {
    int num_features = sizeof(cpu_feature_table) / sizeof(cpu_feature_table[0]);

    boot_printf("CPU Features:\n");
    for (int i = 0; i < num_features; i++) {
        if (boot_cpu_has_feature(cpu_feature_table[i].bit, cpu_feature_table[i].reg)) {
            boot_printf("  [YES] %s\n", cpu_feature_table[i].name);
        }
    }
}

/*
 * Get APIC ID of the BSP
 */
uint32_t boot_cpu_get_apic_id(void) {
    return cpu_apic_id;
}

/*
 * Get number of CPU cores detected
 */
uint32_t boot_cpu_get_cores(void) {
    return cpu_cores;
}

/*
 * Enable SSE/SSE2/SSE3/SSSE3/SSE4.1/SSE4.2/AVX in CR4
 */
void boot_cpu_enable_sse(void) {
    uint64_t cr4 = read_cr4();
    cr4 |= (1 << 9);   /* OSFXSR */
    cr4 |= (1 << 10);  /* OSXMMEXCPT */
    write_cr4(cr4);
}

/*
 * Enable XSAVE support
 */
void boot_cpu_enable_xsave(void) {
    if (boot_cpu_has_feature(26, 1)) {  /* XSAVE feature */
        uint64_t cr4 = read_cr4();
        cr4 |= (1 << 18);  /* OSXSAVE */
        write_cr4(cr4);

        /* Enable XMM (bit 1) and YMM (bit 2) state components */
        xsetbv(0, 0x07);
    }
}

/*
 * Get the CPU's time stamp counter frequency (approximate)
 */
uint64_t boot_cpu_estimate_tsc_freq(void) {
    /* Use calibration against a known timer */
    /* This is a simplified calibration */
    uint64_t tsc_start = read_tsc();

    /* Simple delay loop */
    for (volatile int i = 0; i < 1000000; i++) {
        /* Busy wait */
    }

    uint64_t tsc_end = read_tsc();
    return tsc_end - tsc_start;
}

/*
 * Read the LAPIC timer frequency calibration
 */
uint32_t boot_cpu_get_lapic_freq(void) {
    /* This would be calibrated against a known timer (e.g., PIT or HPET) */
    /* For now, return a typical value of 100 MHz */
    return 100000000;
}