/*
 * AinosOS - arch/x86_64/msr.h
 * Model-Specific Register definitions
 */

#ifndef AINOS_ARCH_X86_64_MSR_H
#define AINOS_ARCH_X86_64_MSR_H

#include <types.h>

/* Read MSR */
static inline uint64_t rdmsr(uint32_t msr) {
    uint32_t lo, hi;
    __asm__ volatile("rdmsr" : "=a"(lo), "=d"(hi) : "c"(msr));
    return ((uint64_t)hi << 32) | lo;
}

/* Write MSR */
static inline void wrmsr(uint32_t msr, uint64_t value) {
    __asm__ volatile("wrmsr" ::
        "a"((uint32_t)(value & 0xFFFFFFFF)),
        "d"((uint32_t)(value >> 32)),
        "c"(msr));
}

/* Write MSR with specific index (safe variant) */
static inline void wrmsr_safe(uint32_t msr, uint64_t value) {
    /* Check if MSR exists before writing */
    uint32_t eax, ebx, ecx, edx;
    cpuid(0x0F, &eax, &ebx, &ecx, &edx); /* Query feature flags */
    /* Write anyway — the CPU will #GP if unsupported */
    wrmsr(msr, value);
}

/* MSR ranges */
#define MSR_IA32_P5_MC_ADDR         0x00000000
#define MSR_IA32_P5_MC_TYPE         0x00000001
#define MSR_IA32_MONITOR_FILTER     0x00000006
#define MSR_IA32_TIME_STAMP_COUNTER 0x00000010
#define MSR_IA32_PLATFORM_ID        0x00000017
#define MSR_IA32_APIC_BASE          0x0000001B
#define MSR_IA32_FEATURE_CONTROL    0x0000003A
#define MSR_IA32_TSC_ADJUST         0x0000003B
#define MSR_IA32_BIOS_UPDT_TRIG     0x00000079
#define MSR_IA32_BIOS_SIGN_ID       0x0000008B
#define MSR_IA32_SGXLEPUBKEYHASH0   0x0000008C
#define MSR_IA32_SGXLEPUBKEYHASH1   0x0000008D
#define MSR_IA32_SGXLEPUBKEYHASH2   0x0000008E
#define MSR_IA32_SGXLEPUBKEYHASH3   0x0000008F
#define MSR_IA32_DEBUGCTL           0x000001D9
#define MSR_IA32_SMRR_PHYSBASE      0x000001F2
#define MSR_IA32_SMRR_PHYSMASK      0x000001F3
#define MSR_IA32_PLATFORM_DCA_CAP   0x000001F8
#define MSR_IA32_CPU_DCA_CAP        0x000001F9
#define MSR_IA32_DCA_0_PM           0x000001FA
#define MSR_IA32_MTRRCAP            0x000000FE
#define MSR_IA32_MTRR_PHYSBASE0     0x00000200
#define MSR_IA32_MTRR_PHYSMASK0     0x00000201
#define MSR_IA32_MTRR_PHYSBASE1     0x00000202
#define MSR_IA32_MTRR_PHYSMASK1     0x00000203
#define MSR_IA32_MTRR_PHYSBASE2     0x00000204
#define MSR_IA32_MTRR_PHYSMASK2     0x00000205
#define MSR_IA32_MTRR_PHYSBASE3     0x00000206
#define MSR_IA32_MTRR_PHYSMASK3     0x00000207
#define MSR_IA32_MTRR_PHYSBASE4     0x00000208
#define MSR_IA32_MTRR_PHYSMASK4     0x00000209
#define MSR_IA32_MTRR_PHYSBASE5     0x0000020A
#define MSR_IA32_MTRR_PHYSMASK5     0x0000020B
#define MSR_IA32_MTRR_PHYSBASE6     0x0000020C
#define MSR_IA32_MTRR_PHYSMASK6     0x0000020D
#define MSR_IA32_MTRR_PHYSBASE7     0x0000020E
#define MSR_IA32_MTRR_PHYSMASK7     0x0000020F
#define MSR_IA32_MTRR_FIX64K_00000  0x00000250
#define MSR_IA32_MTRR_FIX16K_80000  0x00000258
#define MSR_IA32_MTRR_FIX16K_A0000  0x00000259
#define MSR_IA32_MTRR_FIX4K_C0000   0x00000268
#define MSR_IA32_MTRR_FIX4K_C8000   0x00000269
#define MSR_IA32_MTRR_FIX4K_D0000   0x0000026A
#define MSR_IA32_MTRR_FIX4K_D8000   0x0000026B
#define MSR_IA32_MTRR_FIX4K_E0000   0x0000026C
#define MSR_IA32_MTRR_FIX4K_E8000   0x0000026D
#define MSR_IA32_MTRR_FIX4K_F0000   0x0000026E
#define MSR_IA32_MTRR_FIX4K_F8000   0x0000026F
#define MSR_IA32_PAT                0x00000277
#define MSR_IA32_MC0_CTL2           0x00000280
#define MSR_IA32_MC1_CTL2           0x00000281
#define MSR_IA32_MC2_CTL2           0x00000282
#define MSR_IA32_MC3_CTL2           0x00000283
#define MSR_IA32_MC4_CTL2           0x00000284
#define MSR_IA32_MC5_CTL2           0x00000285
#define MSR_IA32_MC6_CTL2           0x00000286
#define MSR_IA32_MC7_CTL2           0x00000287
#define MSR_IA32_MC8_CTL2           0x00000288
#define MSR_IA32_MTRR_DEF_TYPE      0x000002FF
#define MSR_IA32_APIC_ICR           0x00000310
#define MSR_IA32_SYSENTER_CS        0x00000174
#define MSR_IA32_SYSENTER_ESP       0x00000175
#define MSR_IA32_SYSENTER_EIP       0x00000176
#define MSR_IA32_MCG_CAP            0x00000179
#define MSR_IA32_MCG_STATUS         0x0000017A
#define MSR_IA32_MCG_CTL           0x0000017B
#define MSR_IA32_DEBUGCTLMSR        0x000001D9
#define MSR_IA32_LASTBRANCHFROMIP   0x000001DB
#define MSR_IA32_LASTBRANCHTOIP     0x000001DC
#define MSR_IA32_LASTINTFROMIP      0x000001DD
#define MSR_IA32_LASTINTTOIP        0x000001DE
#define MSR_IA32_ROB_CR_BKPT        0x000001E0
#define MSR_IA32_MISC_ENABLE        0x000001A0
#define MSR_IA32_TSC_DEADLINE       0x000006E0
#define MSR_IA32_PKG_HDC_CTL        0x000006DA
#define MSR_IA32_PM_ENABLE          0x00000770
#define MSR_IA32_HWP_CAPABILITIES   0x00000771
#define MSR_IA32_HWP_REQUEST_PKG    0x00000772
#define MSR_IA32_HWP_INTERRUPT      0x00000773
#define MSR_IA32_HWP_REQUEST        0x00000774
#define MSR_IA32_HWP_STATUS         0x00000777
#define MSR_IA32_ENERGY_PERF_BIAS   0x000001B0
#define MSR_IA32_PACKAGE_THERM_STATUS 0x000001B1
#define MSR_IA32_PACKAGE_THERM_INTERRUPT 0x000001B2
#define MSR_IA32_THERM_STATUS       0x0000019C
#define MSR_IA32_THERM_INTERRUPT    0x0000019B
#define MSR_IA32_CLOCK_MODULATION   0x0000019A
#define MSR_IA32_MPERF              0x000000E7
#define MSR_IA32_APERF              0x000000E8
#define MSR_IA32_PERF_STATUS        0x00000198
#define MSR_IA32_PERF_CTL           0x00000199
#define MSR_IA32_FIXED_CTR0         0x00000309
#define MSR_IA32_FIXED_CTR1         0x0000030A
#define MSR_IA32_FIXED_CTR2         0x0000030B
#define MSR_IA32_PERF_GLOBAL_STATUS 0x0000038E
#define MSR_IA32_PERF_GLOBAL_CTRL   0x0000038F
#define MSR_IA32_PERF_GLOBAL_OVF_CTRL 0x00000390
#define MSR_IA32_PEBS_ENABLE        0x000003F1
#define MSR_IA32_DS_AREA            0x00000600
#define MSR_IA32_TSC_DEADLINE       0x000006E0
#define MSR_IA32_SPEC_CTRL          0x00000048
#define MSR_IA32_PRED_CMD           0x00000049
#define MSR_IA32_FLUSH_CMD          0x0000010B
#define MSR_IA32_ARCH_CAPABILITIES  0x0000010A
#define MSR_IA32_CORE_CAPABILITIES  0x000000CF
#define MSR_IA32_UMWAIT_CONTROL     0x00000E00
#define MSR_IA32_XFD                0x00001C00
#define MSR_IA32_XFD_ERR            0x00001C01

/* x2APIC MSRs */
#define MSR_IA32_X2APIC_BASE        0x00000800
#define MSR_IA32_X2APIC_APICID      0x00000802
#define MSR_IA32_X2APIC_VERSION     0x00000803
#define MSR_IA32_X2APIC_TPR         0x00000808
#define MSR_IA32_X2APIC_PPR         0x0000080A
#define MSR_IA32_X2APIC_EOI         0x0000080B
#define MSR_IA32_X2APIC_RRD         0x0000080C
#define MSR_IA32_X2APIC_LDR         0x0000080D
#define MSR_IA32_X2APIC_SVR         0x0000080F
#define MSR_IA32_X2APIC_ISR0        0x00000810
#define MSR_IA32_X2APIC_ISR1        0x00000811
#define MSR_IA32_X2APIC_ISR2        0x00000812
#define MSR_IA32_X2APIC_ISR3        0x00000813
#define MSR_IA32_X2APIC_ISR4        0x00000814
#define MSR_IA32_X2APIC_ISR5        0x00000815
#define MSR_IA32_X2APIC_ISR6        0x00000816
#define MSR_IA32_X2APIC_ISR7        0x00000817
#define MSR_IA32_X2APIC_TMR0        0x00000818
#define MSR_IA32_X2APIC_TMR1        0x00000819
#define MSR_IA32_X2APIC_TMR2        0x0000081A
#define MSR_IA32_X2APIC_TMR3        0x0000081B
#define MSR_IA32_X2APIC_TMR4        0x0000081C
#define MSR_IA32_X2APIC_TMR5        0x0000081D
#define MSR_IA32_X2APIC_TMR6        0x0000081E
#define MSR_IA32_X2APIC_TMR7        0x0000081F
#define MSR_IA32_X2APIC_IRR0        0x00000820
#define MSR_IA32_X2APIC_IRR1        0x00000821
#define MSR_IA32_X2APIC_IRR2        0x00000822
#define MSR_IA32_X2APIC_IRR3        0x00000823
#define MSR_IA32_X2APIC_IRR4        0x00000824
#define MSR_IA32_X2APIC_IRR5        0x00000825
#define MSR_IA32_X2APIC_IRR6        0x00000826
#define MSR_IA32_X2APIC_IRR7        0x00000827
#define MSR_IA32_X2APIC_ESR         0x00000828
#define MSR_IA32_X2APIC_LVT_CMCI    0x0000082F
#define MSR_IA32_X2APIC_ICR         0x00000830
#define MSR_IA32_X2APIC_LVT_TIMER   0x00000832
#define MSR_IA32_X2APIC_LVT_THERMAL 0x00000833
#define MSR_IA32_X2APIC_LVT_PMI     0x00000834
#define MSR_IA32_X2APIC_LVT_LINT0   0x00000835
#define MSR_IA32_X2APIC_LVT_LINT1   0x00000836
#define MSR_IA32_X2APIC_LVT_ERROR   0x00000837
#define MSR_IA32_X2APIC_INIT_COUNT  0x00000838
#define MSR_IA32_X2APIC_CUR_COUNT   0x00000839
#define MSR_IA32_X2APIC_DIV_CONF    0x0000083E
#define MSR_IA32_X2APIC_SELF_IPI    0x0000083F

/* EFER MSR bits */
#define EFER_SCE                    (1ULL << 0)   /* System Call Extensions */
#define EFER_LME                    (1ULL << 8)   /* Long Mode Enable */
#define EFER_LMA                    (1ULL << 10)  /* Long Mode Active */
#define EFER_NXE                    (1ULL << 11)  /* No-Execute Enable */
#define EFER_SVME                   (1ULL << 12)  /* Secure Virtual Machine Enable */
#define EFER_LMSLE                  (1ULL << 13)  /* Long Mode Segment Limit Enable */
#define EFER_FFXSR                  (1ULL << 14)  /* Fast FXSAVE/FXRSTOR */
#define EFER_TCE                    (1ULL << 15)  /* Translation Cache Extension */

/* MTRR definitions */
#define MTRR_TYPE_UNCACHEABLE       0
#define MTRR_TYPE_WRITE_COMBINING   1
#define MTRR_TYPE_WRITE_THROUGH     4
#define MTRR_TYPE_WRITE_PROTECT     5
#define MTRR_TYPE_WRITE_BACK        6
#define MTRR_DEF_TYPE_ENABLE        (1ULL << 11)
#define MTRR_DEF_TYPE_FIXED_ENABLE  (1ULL << 10)

/* PAT (Page Attribute Table) */
#define PAT_UNCACHED                0
#define PAT_WRITE_COMBINING         1
#define PAT_WRITE_THROUGH           4
#define PAT_WRITE_PROTECT           5
#define PAT_WRITE_BACK              6
#define PAT_UNCACHED_UC_MINUS       7

/* MTRR physbase/mask bits */
#define MTRR_PHYSBASE_VALID         (1ULL << 11)
#define MTRR_PHYSMASK_VALID         (1ULL << 11)

/* Feature control bits (MSR_IA32_FEATURE_CONTROL) */
#define FEATURE_CONTROL_LOCK        (1ULL << 0)
#define FEATURE_CONTROL_VMXON       (1ULL << 2)
#define FEATURE_CONTROL_SENTER      (1ULL << 1)
#define FEATURE_CONTROL_SGX         (1ULL << 18)

/* Misc. enable bits */
#define MISC_ENABLE_FAST_STRING     (1ULL << 0)
#define MISC_ENABLE_TCC             (1ULL << 1)
#define MISC_ENABLE_BTS_UNAVAIL     (1ULL << 11)
#define MISC_ENABLE_PEBS_UNAVAIL    (1ULL << 12)
#define MISC_ENABLE_ENHANCED_SPEEDSTEP (1ULL << 16)
#define MISC_ENABLE_MWAIT           (1ULL << 18)
#define MISC_ENABLE_LIMIT_CPUID     (1ULL << 22)
#define MISC_ENABLE_XD_BIT_DISABLE  (1ULL << 34)
#define MISC_ENABLE_TURBO_DISABLE   (1ULL << 38)

/* MTRR base/mask extraction */
#define MTRR_PHYSBASE_PHYS(base)    ((base) & ~0xFFFULL)
#define MTRR_PHYSMASK_PHYS(mask)    ((mask) & ~0xFFFULL)
#define MTRR_PHYSMASK_VALID_BIT     (1ULL << 11)

/* IA32_APIC_BASE bits */
#define APIC_BASE_BSP               (1ULL << 8)
#define APIC_BASE_X2APIC            (1ULL << 10)
#define APIC_BASE_ENABLE            (1ULL << 11)
#define APIC_BASE_PHYS_ADDR_MASK    0xFFFFFF000ULL
#define APIC_BASE_PHYS_ADDR(msr)    ((msr) & APIC_BASE_PHYS_ADDR_MASK)

/* LAPIC register offsets (for xAPIC mode) */
#define LAPIC_ID                    0x020
#define LAPIC_VERSION               0x030
#define LAPIC_TPR                   0x080
#define LAPIC_APR                   0x090
#define LAPIC_PPR                   0x0A0
#define LAPIC_EOI                   0x0B0
#define LAPIC_RRD                   0x0C0
#define LAPIC_LDR                   0x0D0
#define LAPIC_DFR                   0x0E0
#define LAPIC_SVR                   0x0F0
#define LAPIC_ISR                   0x100
#define LAPIC_TMR                   0x180
#define LAPIC_IRR                   0x200
#define LAPIC_ESR                   0x280
#define LAPIC_ICR_LOW               0x300
#define LAPIC_ICR_HIGH              0x310
#define LAPIC_LVT_TIMER             0x320
#define LAPIC_LVT_THERMAL           0x330
#define LAPIC_LVT_PERFMON           0x340
#define LAPIC_LVT_LINT0             0x350
#define LAPIC_LVT_LINT1             0x360
#define LAPIC_LVT_ERROR             0x370
#define LAPIC_INIT_COUNT            0x380
#define LAPIC_CUR_COUNT             0x390
#define LAPIC_DIV_CONF              0x3E0

#endif /* AINOS_ARCH_X86_64_MSR_H */