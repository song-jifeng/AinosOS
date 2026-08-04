/*
 * AinosOS - arch/arm64/registers.h
 * AArch64 system register definitions
 */

#ifndef AINOS_ARCH_ARM64_REGISTERS_H
#define AINOS_ARCH_ARM64_REGISTERS_H

#include <types.h>

/* CurrentEL - Current Exception Level */
static inline uint64_t read_current_el(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, current_el" : "=r"(val));
    return val;
}

/* DAIF - Interrupt mask bits */
static inline uint64_t read_daif(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, daif" : "=r"(val));
    return val;
}

static inline void write_daif(uint64_t val) {
    __asm__ volatile("msr daif, %0" :: "r"(val));
}

/* SCTLR_EL1 - System Control Register */
static inline uint64_t read_sctlr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, sctlr_el1" : "=r"(val));
    return val;
}

static inline void write_sctlr_el1(uint64_t val) {
    __asm__ volatile("msr sctlr_el1, %0" :: "r"(val) : "memory");
}

/* SCTLR bits */
#define SCTLR_EL1_M           (1UL << 0)   /* MMU enable */
#define SCTLR_EL1_A           (1UL << 1)   /* Alignment check */
#define SCTLR_EL1_C           (1UL << 2)   /* Cache enable */
#define SCTLR_EL1_SA          (1UL << 3)   /* Stack alignment */
#define SCTLR_EL1_I           (1UL << 12)  /* Instruction cache */
#define SCTLR_EL1_WXN         (1UL << 19)  /* Write permission implies XN */
#define SCTLR_EL1_EE          (1UL << 25)  /* Endianness */
#define SCTLR_EL1_IESB        (1UL << 21)  /* Implicit error synchronization */

/* TCR_EL1 - Translation Control Register */
static inline uint64_t read_tcr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, tcr_el1" : "=r"(val));
    return val;
}

static inline void write_tcr_el1(uint64_t val) {
    __asm__ volatile("msr tcr_el1, %0" :: "r"(val) : "memory");
}

/* TCR bits */
#define TCR_TG0_4K            (0UL << 14)
#define TCR_TG0_16K           (2UL << 14)
#define TCR_TG0_64K           (1UL << 14)
#define TCR_SH0_INNER         (3UL << 12)
#define TCR_ORGN0_WB_WA       (1UL << 10)
#define TCR_IRGN0_WB_WA       (1UL << 8)
#define TCR_T0SZ(x)           ((64 - (x)) << 0)
#define TCR_PS_4GB            (0UL << 16)
#define TCR_PS_64GB           (1UL << 16)
#define TCR_PS_1TB            (2UL << 16)
#define TCR_PS_4TB            (3UL << 16)
#define TCR_PS_16TB           (4UL << 16)
#define TCR_PS_256TB          (5UL << 16)

/* MAIR_EL1 - Memory Attribute Indirection Register */
static inline uint64_t read_mair_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, mair_el1" : "=r"(val));
    return val;
}

static inline void write_mair_el1(uint64_t val) {
    __asm__ volatile("msr mair_el1, %0" :: "r"(val) : "memory");
}

/* TTBR0_EL1 / TTBR1_EL1 - Translation Table Base Registers */
static inline uint64_t read_ttbr0_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, ttbr0_el1" : "=r"(val));
    return val;
}

static inline void write_ttbr0_el1(uint64_t val) {
    __asm__ volatile("msr ttbr0_el1, %0" :: "r"(val) : "memory");
}

static inline uint64_t read_ttbr1_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, ttbr1_el1" : "=r"(val));
    return val;
}

static inline void write_ttbr1_el1(uint64_t val) {
    __asm__ volatile("msr ttbr1_el1, %0" :: "r"(val) : "memory");
}

/* VBAR_EL1 - Vector Base Address Register */
static inline uint64_t read_vbar_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, vbar_el1" : "=r"(val));
    return val;
}

static inline void write_vbar_el1(uint64_t val) {
    __asm__ volatile("msr vbar_el1, %0" :: "r"(val) : "memory");
}

/* ESR_EL1 - Exception Syndrome Register */
static inline uint64_t read_esr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, esr_el1" : "=r"(val));
    return val;
}

/* FAR_EL1 - Fault Address Register */
static inline uint64_t read_far_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, far_el1" : "=r"(val));
    return val;
}

/* ELR_EL1 - Exception Link Register */
static inline uint64_t read_elr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, elr_el1" : "=r"(val));
    return val;
}

static inline void write_elr_el1(uint64_t val) {
    __asm__ volatile("msr elr_el1, %0" :: "r"(val));
}

/* SPSR_EL1 - Saved Program Status Register */
static inline uint64_t read_spsr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, spsr_el1" : "=r"(val));
    return val;
}

static inline void write_spsr_el1(uint64_t val) {
    __asm__ volatile("msr spsr_el1, %0" :: "r"(val));
}

/* SPSR bits */
#define SPSR_MASK_D           (1 << 9)
#define SPSR_MASK_A           (1 << 8)
#define SPSR_MASK_I           (1 << 7)
#define SPSR_MASK_F           (1 << 6)
#define SPSR_EL0t             (0 << 0)
#define SPSR_EL1t             (4 << 0)
#define SPSR_EL1h             (5 << 0)
#define SPSR_EL2t             (8 << 0)
#define SPSR_EL2h             (9 << 0)

/* Counter-timer */
static inline uint64_t read_cntpct_el0(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, cntpct_el0" : "=r"(val));
    return val;
}

static inline uint64_t read_cntfrq_el0(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(val));
    return val;
}

static inline void write_cntfrq_el0(uint64_t val) {
    __asm__ volatile("msr cntfrq_el0, %0" :: "r"(val));
}

/* MPIDR_EL1 - Multiprocessor Affinity Register */
static inline uint64_t read_mpidr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, mpidr_el1" : "=r"(val));
    return val;
}

/* REVIDR_EL1 - Revision ID */
static inline uint64_t read_revidr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, revidr_el1" : "=r"(val));
    return val;
}

/* MIDR_EL1 - Main ID Register */
static inline uint64_t read_midr_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, midr_el1" : "=r"(val));
    return val;
}

/* ID_AA64MMFR0_EL1 - AArch64 Memory Model Feature Register */
static inline uint64_t read_id_aa64mmfr0_el1(void) {
    uint64_t val;
    __asm__ volatile("mrs %0, id_aa64mmfr0_el1" : "=r"(val));
    return val;
}

/* Cache operations */
static inline void dc_ivac(void *addr) {
    __asm__ volatile("dc ivac, %0" :: "r"(addr) : "memory");
}

static inline void dc_cvac(void *addr) {
    __asm__ volatile("dc cvac, %0" :: "r"(addr) : "memory");
}

static inline void dc_cvau(void *addr) {
    __asm__ volatile("dc cvau, %0" :: "r"(addr) : "memory");
}

static inline void dc_civac(void *addr) {
    __asm__ volatile("dc civac, %0" :: "r"(addr) : "memory");
}

static inline void ic_ivau(void *addr) {
    __asm__ volatile("ic ivau, %0" :: "r"(addr) : "memory");
}

static inline void dsb(void) {
    __asm__ volatile("dsb sy" ::: "memory");
}

static inline void dmb(void) {
    __asm__ volatile("dmb sy" ::: "memory");
}

static inline void isb(void) {
    __asm__ volatile("isb" ::: "memory");
}

/* WFI/WFE */
static inline void wfi(void) {
    __asm__ volatile("wfi");
}

static inline void wfe(void) {
    __asm__ volatile("wfe");
}

/* SEV */
static inline void sev(void) {
    __asm__ volatile("sev");
}

/* Spin-table release */
static inline void sevl(void) {
    __asm__ volatile("sevl");
}

/* Get stack pointer */
static inline uint64_t read_sp(void) {
    uint64_t val;
    __asm__ volatile("mov %0, sp" : "=r"(val));
    return val;
}

/* Get frame pointer */
static inline uint64_t read_fp(void) {
    uint64_t val;
    __asm__ volatile("mov %0, x29" : "=r"(val));
    return val;
}

/* Get link register */
static inline uint64_t read_lr(void) {
    uint64_t val;
    __asm__ volatile("mov %0, x30" : "=r"(val));
    return val;
}

/* GICC / GIC CPU interface */
#define GIC_CPU_IF_BASE     0x2F000000
#define GIC_DIST_BASE       0x2F001000

/* GIC registers */
#define GIC_ICC_EOIR        (GIC_CPU_IF_BASE + 0x0010)
#define GIC_ICC_IAR         (GIC_CPU_IF_BASE + 0x000C)
#define GIC_ICC_PMR         (GIC_CPU_IF_BASE + 0x0004)
#define GIC_ICC_CTLR        (GIC_CPU_IF_BASE + 0x0000)

/* UART (PL011) */
#define UART_DR             0x000
#define UART_FR             0x018
#define UART_IBRD           0x024
#define UART_FBRD           0x028
#define UART_LCR_H          0x02C
#define UART_CR             0x030
#define UART_IFLS           0x034
#define UART_IMSC           0x038
#define UART_RIS            0x03C
#define UART_MIS            0x040
#define UART_ICR            0x044

#define UART_FR_TXFF        (1 << 5)
#define UART_FR_RXFE        (1 << 4)
#define UART_CR_UARTEN      (1 << 0)
#define UART_CR_TXE         (1 << 8)
#define UART_CR_RXE         (1 << 9)
#define UART_LCR_H_8BIT     (0x60)
#define UART_LCR_H_FEN      (1 << 4)

#endif /* AINOS_ARCH_ARM64_REGISTERS_H */