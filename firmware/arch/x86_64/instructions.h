/*
 * AinosOS - arch/x86_64/instructions.h
 * Inline assembly instruction wrappers
 */

#ifndef AINOS_ARCH_X86_64_INSTRUCTIONS_H
#define AINOS_ARCH_X86_64_INSTRUCTIONS_H

#include <types.h>

/* I/O port operations */
static inline uint8_t inb(uint16_t port) {
    uint8_t val;
    __asm__ volatile("inb %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline uint16_t inw(uint16_t port) {
    uint16_t val;
    __asm__ volatile("inw %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline uint32_t inl(uint16_t port) {
    uint32_t val;
    __asm__ volatile("inl %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline void outb(uint16_t port, uint8_t val) {
    __asm__ volatile("outb %0, %1" :: "a"(val), "Nd"(port));
}

static inline void outw(uint16_t port, uint16_t val) {
    __asm__ volatile("outw %0, %1" :: "a"(val), "Nd"(port));
}

static inline void outl(uint16_t port, uint32_t val) {
    __asm__ volatile("outl %0, %1" :: "a"(val), "Nd"(port));
}

/* I/O string operations */
static inline void insb(uint16_t port, void *addr, size_t count) {
    __asm__ volatile("rep insb" : "+D"(addr), "+c"(count) : "d"(port) : "memory");
}

static inline void insw(uint16_t port, void *addr, size_t count) {
    __asm__ volatile("rep insw" : "+D"(addr), "+c"(count) : "d"(port) : "memory");
}

static inline void insl(uint16_t port, void *addr, size_t count) {
    __asm__ volatile("rep insl" : "+D"(addr), "+c"(count) : "d"(port) : "memory");
}

static inline void outsb(uint16_t port, const void *addr, size_t count) {
    __asm__ volatile("rep outsb" : "+S"(addr), "+c"(count) : "d"(port));
}

static inline void outsw(uint16_t port, const void *addr, size_t count) {
    __asm__ volatile("rep outsw" : "+S"(addr), "+c"(count) : "d"(port));
}

static inline void outsl(uint16_t port, const void *addr, size_t count) {
    __asm__ volatile("rep outsl" : "+S"(addr), "+c"(count) : "d"(port));
}

/* I/O delay */
static inline void io_delay(void) {
    outb(0x80, 0);
}

/* Port 0x80 dummy write for microsecond-scale delay */
static inline void io_delay_n(int count) {
    for (int i = 0; i < count; i++) {
        io_delay();
    }
}

/* Flags operations */
static inline uint64_t save_flags(void) {
    uint64_t flags;
    __asm__ volatile("pushfq; popq %0" : "=rm"(flags) :: "memory");
    return flags;
}

static inline void restore_flags(uint64_t flags) {
    __asm__ volatile("pushq %0; popfq" :: "g"(flags) : "memory", "cc");
}

/* Safe CLI/STI with save/restore */
static inline uint64_t irq_save(void) {
    uint64_t flags = save_flags();
    cli();
    return flags;
}

static inline void irq_restore(uint64_t flags) {
    restore_flags(flags);
}

/* ENTER/LEAVE */
static inline void enter_64bit_mode(void) {
    /* Far return to switch to 64-bit code segment */
    __asm__ volatile("pushq %0; retfq" :: "i"(0), "r"(0x08) : "memory");
}

/* Memory fence */
static inline void mfence(void) {
    __asm__ volatile("mfence" ::: "memory");
}

static inline void sfence(void) {
    __asm__ volatile("sfence" ::: "memory");
}

static inline void lfence(void) {
    __asm__ volatile("lfence" ::: "memory");
}

/* Cache control */
static inline void clflush(void *addr) {
    __asm__ volatile("clflush (%0)" :: "r"(addr) : "memory");
}

static inline void clflushopt(void *addr) {
    __asm__ volatile(".byte 0x66, 0x0f, 0xae, 0x38" :: "r"(addr) : "memory");
}

static inline void clwb(void *addr) {
    __asm__ volatile(".byte 0x66, 0x0f, 0xae, 0x30" :: "r"(addr) : "memory");
}

/* Monitor/Mwait */
static inline void monitor(void *addr) {
    __asm__ volatile("monitor" :: "a"(addr), "c"(0), "d"(0) : "memory");
}

static inline void mwait(uint32_t hints, uint32_t extensions) {
    __asm__ volatile("mwait" :: "a"(hints), "c"(extensions) : "memory");
}

/* UMWAIT / TPAUSE - if supported */
static inline void umwait(uint32_t hints, uint64_t timeout) {
    __asm__ volatile("umwait %0" :: "r"(hints), "a"((uint32_t)timeout), "d"((uint32_t)(timeout >> 32)));
}

/* RDRAND / RDSEED */
static inline int rdrand(uint64_t *val) {
    uint8_t ok;
    __asm__ volatile("rdrand %0; setc %1" : "=r"(*val), "=qm"(ok));
    return ok;
}

static inline int rdseed(uint64_t *val) {
    uint8_t ok;
    __asm__ volatile("rdseed %0; setc %1" : "=r"(*val), "=qm"(ok));
    return ok;
}

/* Read time-stamp counter with processor ID */
static inline uint64_t read_tscp(uint32_t *aux) {
    uint32_t lo, hi;
    __asm__ volatile("rdtscp" : "=a"(lo), "=d"(hi), "=c"(*aux));
    return ((uint64_t)hi << 32) | lo;
}

/* CPUID with leaf 0x4B (XSAVE area size) */
static inline uint64_t xgetbv(uint32_t xcr) {
    uint32_t lo, hi;
    __asm__ volatile("xgetbv" : "=a"(lo), "=d"(hi) : "c"(xcr));
    return ((uint64_t)hi << 32) | lo;
}

static inline void xsetbv(uint32_t xcr, uint64_t val) {
    __asm__ volatile("xsetbv" :: "a"((uint32_t)val), "d"((uint32_t)(val >> 32)), "c"(xcr));
}

/* Read performance counter */
static inline uint64_t read_pmc(uint32_t counter) {
    uint32_t lo, hi;
    __asm__ volatile("rdpmc" : "=a"(lo), "=d"(hi) : "c"(counter));
    return ((uint64_t)hi << 32) | lo;
}

/* CMOS/RTC access */
static inline uint8_t cmos_read(uint8_t reg) {
    outb(0x70, reg);
    return inb(0x71);
}

static inline void cmos_write(uint8_t reg, uint8_t val) {
    outb(0x70, reg);
    outb(0x71, val);
}

/* NMI enable/disable */
static inline void disable_nmi(void) {
    outb(0x70, inb(0x70) | 0x80);
}

static inline void enable_nmi(void) {
    outb(0x70, inb(0x70) & 0x7F);
}

/* Port 0x92 - A20 gate and reset control */
static inline void enable_a20(void) {
    outb(0x92, inb(0x92) | 0x02);
}

/* Triple fault to reset */
static inline void triple_fault_reset(void) {
    /* Load a zero-length IDT to cause triple fault on next interrupt */
    struct PACKED {
        uint16_t limit;
        uint64_t base;
    } idtr = { 0, 0 };
    __asm__ volatile("lidt %0; int3" :: "m"(idtr) : "memory");
    for (;;) hlt();
}

/* BCD <-> binary conversion helpers */
static inline uint8_t bcd_to_bin(uint8_t bcd) {
    return (bcd & 0x0F) + ((bcd >> 4) * 10);
}

static inline uint8_t bin_to_bcd(uint8_t bin) {
    return ((bin / 10) << 4) | (bin % 10);
}

#endif /* AINOS_ARCH_X86_64_INSTRUCTIONS_H */