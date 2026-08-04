/*
 * AinosOS - arch/x86_64/registers.h
 * x86_64 CPU register definitions
 */

#ifndef AINOS_ARCH_X86_64_REGISTERS_H
#define AINOS_ARCH_X86_64_REGISTERS_H

#include <types.h>

/* Control registers */
#define CR0_PE                  (1UL << 0)   /* Protection Enable */
#define CR0_MP                  (1UL << 1)   /* Monitor Coprocessor */
#define CR0_EM                  (1UL << 2)   /* Emulation */
#define CR0_TS                  (1UL << 3)   /* Task Switched */
#define CR0_ET                  (1UL << 4)   /* Extension Type */
#define CR0_NE                  (1UL << 5)   /* Numeric Error */
#define CR0_WP                  (1UL << 16)  /* Write Protect */
#define CR0_AM                  (1UL << 18)  /* Alignment Mask */
#define CR0_NW                  (1UL << 29)  /* Not Write-through */
#define CR0_CD                  (1UL << 30)  /* Cache Disable */
#define CR0_PG                  (1UL << 31)  /* Paging */

#define CR4_VME                 (1UL << 0)   /* Virtual 8086 Mode Extensions */
#define CR4_PVI                 (1UL << 1)   /* Protected-mode Virtual Interrupts */
#define CR4_TSD                 (1UL << 2)   /* Time Stamp Disable */
#define CR4_DE                  (1UL << 3)   /* Debugging Extensions */
#define CR4_PSE                 (1UL << 4)   /* Page Size Extension */
#define CR4_PAE                 (1UL << 5)   /* Physical Address Extension */
#define CR4_MCE                 (1UL << 6)   /* Machine Check Enable */
#define CR4_PGE                 (1UL << 7)   /* Page Global Enable */
#define CR4_PCE                 (1UL << 8)   /* Performance-Monitoring Counter Enable */
#define CR4_OSFXSR              (1UL << 9)   /* OS Support for FXSAVE/FXRSTOR */
#define CR4_OSXMMEXCPT          (1UL << 10)  /* OS Support for Unmasked SIMD FPU Exceptions */
#define CR4_UMIP                (1UL << 11)  /* User-Mode Instruction Prevention */
#define CR4_LA57                (1UL << 12)  /* 57-bit Linear Addresses */
#define CR4_VMXE                (1UL << 13)  /* VMX Enable */
#define CR4_SMXE                (1UL << 14)  /* SMX Enable */
#define CR4_FSGSBASE            (1UL << 16)  /* Enables RDFSBASE/RDGSBASE/WRFSBASE/WRGSBASE */
#define CR4_PCIDE               (1UL << 17)  /* PCID Enable */
#define CR4_OSXSAVE             (1UL << 18)  /* XSAVE and Processor Extended States Enable */
#define CR4_KL                  (1UL << 19)  /* Key Locker Enable */
#define CR4_SMEP                (1UL << 20)  /* Supervisor Mode Execution Prevention */
#define CR4_SMAP                (1UL << 21)  /* Supervisor Mode Access Prevention */
#define CR4_PKE                 (1UL << 22)  /* Protection Key Enable */
#define CR4_CET                 (1UL << 23)  /* Control-flow Enforcement Technology */

/* CR0 read/write */
static inline uint64_t read_cr0(void) {
    uint64_t val;
    __asm__ volatile("mov %%cr0, %0" : "=r"(val));
    return val;
}

static inline void write_cr0(uint64_t val) {
    __asm__ volatile("mov %0, %%cr0" :: "r"(val) : "memory");
}

/* CR2 (page fault linear address) */
static inline uint64_t read_cr2(void) {
    uint64_t val;
    __asm__ volatile("mov %%cr2, %0" : "=r"(val));
    return val;
}

/* CR3 (page table base) */
static inline uint64_t read_cr3(void) {
    uint64_t val;
    __asm__ volatile("mov %%cr3, %0" : "=r"(val));
    return val;
}

static inline void write_cr3(uint64_t val) {
    __asm__ volatile("mov %0, %%cr3" :: "r"(val) : "memory");
}

/* CR4 read/write */
static inline uint64_t read_cr4(void) {
    uint64_t val;
    __asm__ volatile("mov %%cr4, %0" : "=r"(val));
    return val;
}

static inline void write_cr4(uint64_t val) {
    __asm__ volatile("mov %0, %%cr4" :: "r"(val) : "memory");
}

/* RFLAGS register */
static inline uint64_t read_rflags(void) {
    uint64_t val;
    __asm__ volatile("pushfq; popq %0" : "=r"(val));
    return val;
}

/* Segment registers */
static inline uint16_t read_cs(void) {
    uint16_t val;
    __asm__ volatile("mov %%cs, %0" : "=r"(val));
    return val;
}

static inline uint16_t read_ds(void) {
    uint16_t val;
    __asm__ volatile("mov %%ds, %0" : "=r"(val));
    return val;
}

static inline uint16_t read_es(void) {
    uint16_t val;
    __asm__ volatile("mov %%es, %0" : "=r"(val));
    return val;
}

static inline uint16_t read_fs(void) {
    uint16_t val;
    __asm__ volatile("mov %%fs, %0" : "=r"(val));
    return val;
}

static inline uint16_t read_gs(void) {
    uint16_t val;
    __asm__ volatile("mov %%gs, %0" : "=r"(val));
    return val;
}

static inline uint16_t read_ss(void) {
    uint16_t val;
    __asm__ volatile("mov %%ss, %0" : "=r"(val));
    return val;
}

static inline void load_cs(uint64_t sel) {
    __asm__ volatile("pushq %0; retfq" :: "i"(0), "r"(sel) : "memory");
}

/* GDTR / IDTR */
struct PACKED gdtr_t {
    uint16_t limit;
    uint64_t base;
};

struct PACKED idtr_t {
    uint16_t limit;
    uint64_t base;
};

static inline void lgdt(const struct gdtr_t *gdtr) {
    __asm__ volatile("lgdt (%0)" :: "r"(gdtr) : "memory");
}

static inline void lidt(const struct idtr_t *idtr) {
    __asm__ volatile("lidt (%0)" :: "r"(idtr) : "memory");
}

static inline void ltr(uint16_t sel) {
    __asm__ volatile("ltr %0" :: "r"(sel));
}

/* MSR access */
#define MSR_IA32_APIC_BASE      0x1B
#define MSR_IA32_EFER           0xC0000080
#define MSR_IA32_STAR           0xC0000081
#define MSR_IA32_LSTAR          0xC0000082
#define MSR_IA32_FMASK          0xC0000084
#define MSR_IA32_FS_BASE        0xC0000100
#define MSR_IA32_GS_BASE        0xC0000101
#define MSR_IA32_KERNEL_GS_BASE 0xC0000102
#define MSR_IA32_TSC            0x10
#define MSR_IA32_MTRRCAP        0xFE
#define MSR_IA32_MTRR_PHYSBASE0 0x200
#define MSR_IA32_MTRR_PHYSMASK0 0x201
#define MSR_IA32_MTRR_PHYSBASE1 0x202
#define MSR_IA32_MTRR_PHYSMASK1 0x203
#define MSR_IA32_MTRR_PHYSBASE2 0x204
#define MSR_IA32_MTRR_PHYSMASK2 0x205
#define MSR_IA32_MTRR_PHYSBASE3 0x206
#define MSR_IA32_MTRR_PHYSMASK3 0x207
#define MSR_IA32_MTRR_DEF_TYPE  0x2FF
#define MSR_IA32_PAT            0x277
#define MSR_IA32_SYSENTER_CS    0x174
#define MSR_IA32_SYSENTER_ESP   0x175
#define MSR_IA32_SYSENTER_EIP   0x176
#define MSR_IA32_TSC_DEADLINE   0x6E0
#define MSR_IA32_X2APIC_BASE    0x800
#define MSR_IA32_X2APIC_EOI     0x80B
#define MSR_IA32_X2APIC_TPR     0x808
#define MSR_IA32_X2APIC_SVR     0x80F
#define MSR_IA32_X2APIC_ICR     0x830
#define MSR_IA32_X2APIC_LVT_TIMER   0x832
#define MSR_IA32_X2APIC_LVT_PMI     0x833
#define MSR_IA32_X2APIC_LVT_LINT0   0x835
#define MSR_IA32_X2APIC_LVT_LINT1   0x836
#define MSR_IA32_X2APIC_INIT_COUNT   0x838
#define MSR_IA32_X2APIC_CUR_COUNT    0x839
#define MSR_IA32_X2APIC_DIV_CONF     0x83E
#define MSR_IA32_MISC_ENABLE     0x1A0

/* EFER bits */
#define EFER_SCE                (1UL << 0)   /* System Call Extensions */
#define EFER_LME                (1UL << 8)   /* Long Mode Enable */
#define EFER_LMA                (1UL << 10)  /* Long Mode Active */
#define EFER_NXE                (1UL << 11)  /* No-Execute Enable */
#define EFER_SVME               (1UL << 12)  /* Secure Virtual Machine Enable */
#define EFER_LMSLE              (1UL << 13)  /* Long Mode Segment Limit Enable */
#define EFER_FFXSR              (1UL << 14)  /* Fast FXSAVE/FXRSTOR */

static inline uint64_t read_msr(uint32_t msr) {
    uint32_t lo, hi;
    __asm__ volatile("rdmsr" : "=a"(lo), "=d"(hi) : "c"(msr));
    return ((uint64_t)hi << 32) | lo;
}

static inline void write_msr(uint32_t msr, uint64_t val) {
    __asm__ volatile("wrmsr" :: "a"((uint32_t)val), "d"((uint32_t)(val >> 32)), "c"(msr));
}

/* TSC */
static inline uint64_t read_tsc(void) {
    uint32_t lo, hi;
    __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
    return ((uint64_t)hi << 32) | lo;
}

/* CPUID */
static inline void cpuid(uint32_t leaf, uint32_t *eax, uint32_t *ebx,
                         uint32_t *ecx, uint32_t *edx) {
    __asm__ volatile("cpuid"
        : "=a"(*eax), "=b"(*ebx), "=c"(*ecx), "=d"(*edx)
        : "a"(leaf), "c"(0));
}

static inline void cpuid_ex(uint32_t leaf, uint32_t subleaf,
                            uint32_t *eax, uint32_t *ebx,
                            uint32_t *ecx, uint32_t *edx) {
    __asm__ volatile("cpuid"
        : "=a"(*eax), "=b"(*ebx), "=c"(*ecx), "=d"(*edx)
        : "a"(leaf), "c"(subleaf));
}

/* XSAVE / XRSTOR */
static inline void xsave(void *region, uint64_t mask) {
    __asm__ volatile("xsaveq %0" :: "m"(*(uint8_t*)region), "d"(mask >> 32), "a"(mask));
}

static inline void xrstor(const void *region, uint64_t mask) {
    __asm__ volatile("xrstorq %0" :: "m"(*(uint8_t*)region), "d"(mask >> 32), "a"(mask));
}

/* INVPCID */
static inline void invpcid(uint64_t pcid, uint64_t addr, uint64_t type) {
    struct {
        uint64_t pcid;
        uint64_t addr;
    } desc = { pcid, addr };
    __asm__ volatile("invpcid %0, %1" :: "m"(desc), "r"(type) : "memory");
}

#define INVPCID_INDIVIDUAL_ADDR      0
#define INVPCID_SINGLE_CONTEXT       1
#define INVPCID_ALL_CONTEXT          2
#define INVPCID_ALL_CONTEXT_GLOBAL   3

/* INVLPG */
static inline void invlpg(void *addr) {
    __asm__ volatile("invlpg (%0)" :: "r"(addr) : "memory");
}

/* WBINVD */
static inline void wbinvd(void) {
    __asm__ volatile("wbinvd" ::: "memory");
}

/* HLT */
static inline void hlt(void) {
    __asm__ volatile("hlt");
}

/* PAUSE */
static inline void pause(void) {
    __asm__ volatile("pause");
}

/* CLI / STI */
static inline void cli(void) {
    __asm__ volatile("cli" ::: "memory");
}

static inline void sti(void) {
    __asm__ volatile("sti" ::: "memory");
}

/* Read segment registers */
static inline uint16_t read_tr(void) {
    uint16_t sel;
    __asm__ volatile("str %0" : "=r"(sel));
    return sel;
}

/* Get/set FS/GS base */
static inline uint64_t read_fs_base(void) {
    return read_msr(MSR_IA32_FS_BASE);
}

static inline void write_fs_base(uint64_t base) {
    write_msr(MSR_IA32_FS_BASE, base);
}

static inline uint64_t read_gs_base(void) {
    return read_msr(MSR_IA32_GS_BASE);
}

static inline void write_gs_base(uint64_t base) {
    write_msr(MSR_IA32_GS_BASE, base);
}

static inline uint64_t read_kernel_gs_base(void) {
    return read_msr(MSR_IA32_KERNEL_GS_BASE);
}

static inline void write_kernel_gs_base(uint64_t base) {
    write_msr(MSR_IA32_KERNEL_GS_BASE, base);
}

/* Swap GS */
static inline void swapgs(void) {
    __asm__ volatile("swapgs");
}

#endif /* AINOS_ARCH_X86_64_REGISTERS_H */