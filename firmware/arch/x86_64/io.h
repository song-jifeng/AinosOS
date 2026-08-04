/*
 * AinosOS - arch/x86_64/io.h
 * I/O port operations
 */

#ifndef AINOS_ARCH_X86_64_IO_H
#define AINOS_ARCH_X86_64_IO_H

#include <types.h>

/* Standard I/O port access */
static inline uint8_t io_inb(uint16_t port) {
    uint8_t val;
    __asm__ volatile("inb %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline uint16_t io_inw(uint16_t port) {
    uint16_t val;
    __asm__ volatile("inw %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline uint32_t io_inl(uint16_t port) {
    uint32_t val;
    __asm__ volatile("inl %1, %0" : "=a"(val) : "Nd"(port));
    return val;
}

static inline void io_outb(uint16_t port, uint8_t val) {
    __asm__ volatile("outb %0, %1" :: "a"(val), "Nd"(port));
}

static inline void io_outw(uint16_t port, uint16_t val) {
    __asm__ volatile("outw %0, %1" :: "a"(val), "Nd"(port));
}

static inline void io_outl(uint16_t port, uint32_t val) {
    __asm__ volatile("outl %0, %1" :: "a"(val), "Nd"(port));
}

/* String I/O */
static inline void io_insb(uint16_t port, void *buf, size_t count) {
    __asm__ volatile("rep insb" : "+D"(buf), "+c"(count) : "d"(port) : "memory");
}

static inline void io_insw(uint16_t port, void *buf, size_t count) {
    __asm__ volatile("rep insw" : "+D"(buf), "+c"(count) : "d"(port) : "memory");
}

static inline void io_insl(uint16_t port, void *buf, size_t count) {
    __asm__ volatile("rep insl" : "+D"(buf), "+c"(count) : "d"(port) : "memory");
}

static inline void io_outsb(uint16_t port, const void *buf, size_t count) {
    __asm__ volatile("rep outsb" : "+S"(buf), "+c"(count) : "d"(port));
}

static inline void io_outsw(uint16_t port, const void *buf, size_t count) {
    __asm__ volatile("rep outsw" : "+S"(buf), "+c"(count) : "d"(port));
}

static inline void io_outsl(uint16_t port, const void *buf, size_t count) {
    __asm__ volatile("rep outsl" : "+S"(buf), "+c"(count) : "d"(port));
}

/* I/O delay */
static inline void io_wait(void) {
    io_outb(0x80, 0);
}

/* Read CMOS/RTC */
static inline uint8_t cmos_read(uint8_t reg) {
    io_outb(0x70, reg);
    return io_inb(0x71);
}

static inline void cmos_write(uint8_t reg, uint8_t val) {
    io_outb(0x70, reg);
    io_outb(0x71, val);
}

/* NMI mask */
static inline void cmos_mask_nmi(void) {
    io_outb(0x70, io_inb(0x70) | 0x80);
}

static inline void cmos_unmask_nmi(void) {
    io_outb(0x70, io_inb(0x70) & 0x7F);
}

/* A20 gate */
static inline void enable_a20_gate(void) {
    io_outb(0x92, io_inb(0x92) | 0x02);
}

/* Reset system via keyboard controller */
static inline void reset_via_keyboard(void) {
    io_outb(0x64, 0xFE);
    for (;;) { __asm__ volatile("hlt"); }
}

/* Reset via reset port */
static inline void reset_via_port(void) {
    io_outb(0xCF9, 0x06);
    for (;;) { __asm__ volatile("hlt"); }
}

#endif /* AINOS_ARCH_X86_64_IO_H */