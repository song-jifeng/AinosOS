/*
 * AinosOS - arch/arm64/vectors.S
 * AArch64 exception vector table
 */

.section .text.vectors, "ax"
.align 12

/* Exception vector table for EL1 */
.global exception_vector_table
exception_vector_table:

/* Current EL with SP0 (not used in Linux/Ainos) */
.align 7
    b       sync_el1t_sp0       /* Synchronous */
    b       irq_el1t_sp0        /* IRQ */
    b       fiq_el1t_sp0        /* FIQ */
    b       serr_el1t_sp0       /* SError */

/* Current EL with SPx */
.align 7
    b       sync_el1h_sp        /* Synchronous */
    b       irq_el1h_sp         /* IRQ */
    b       fiq_el1h_sp         /* FIQ */
    b       serr_el1h_sp        /* SError */

/* Lower EL using AArch64 */
.align 7
    b       sync_el0_a64        /* Synchronous */
    b       irq_el0_a64         /* IRQ */
    b       fiq_el0_a64         /* FIQ */
    b       serr_el0_a64        /* SError */

/* Lower EL using AArch32 */
.align 7
    b       sync_el0_a32        /* Synchronous */
    b       irq_el0_a32         /* IRQ */
    b       fiq_el0_a32         /* FIQ */
    b       serr_el0_a32        /* SError */

/* Default handlers */
sync_el1t_sp0:
    mrs     x0, esr_el1
    mrs     x1, far_el1
    mrs     x2, elr_el1
    b       exception_handler

irq_el1t_sp0:
    b       irq_handler

fiq_el1t_sp0:
    b       fiq_handler

serr_el1t_sp0:
    b       serr_handler

sync_el1h_sp:
    /* Save all registers */
    stp     x0, x1, [sp, #-16]!
    stp     x2, x3, [sp, #-16]!
    stp     x4, x5, [sp, #-16]!
    stp     x6, x7, [sp, #-16]!
    stp     x8, x9, [sp, #-16]!
    stp     x10, x11, [sp, #-16]!
    stp     x12, x13, [sp, #-16]!
    stp     x14, x15, [sp, #-16]!
    stp     x16, x17, [sp, #-16]!
    stp     x18, x19, [sp, #-16]!
    stp     x20, x21, [sp, #-16]!
    stp     x22, x23, [sp, #-16]!
    stp     x24, x25, [sp, #-16]!
    stp     x26, x27, [sp, #-16]!
    stp     x28, x29, [sp, #-16]!
    stp     x30, xzr, [sp, #-16]!

    /* Get ESR, FAR, ELR */
    mrs     x0, esr_el1
    mrs     x1, far_el1
    mrs     x2, elr_el1

    /* Call C handler */
    bl      arm64_sync_handler

    /* Restore all registers */
    ldp     x30, xzr, [sp], #16
    ldp     x28, x29, [sp], #16
    ldp     x26, x27, [sp], #16
    ldp     x24, x25, [sp], #16
    ldp     x22, x23, [sp], #16
    ldp     x20, x21, [sp], #16
    ldp     x18, x19, [sp], #16
    ldp     x16, x17, [sp], #16
    ldp     x14, x15, [sp], #16
    ldp     x12, x13, [sp], #16
    ldp     x10, x11, [sp], #16
    ldp     x8, x9, [sp], #16
    ldp     x6, x7, [sp], #16
    ldp     x4, x5, [sp], #16
    ldp     x2, x3, [sp], #16
    ldp     x0, x1, [sp], #16
    eret

irq_el1h_sp:
    sub     sp, sp, #256
    stp     x0, x1, [sp, #0]
    stp     x2, x3, [sp, #16]
    stp     x4, x5, [sp, #32]
    stp     x6, x7, [sp, #48]
    stp     x8, x9, [sp, #64]
    stp     x10, x11, [sp, #80]
    stp     x12, x13, [sp, #96]
    stp     x14, x15, [sp, #112]
    stp     x16, x17, [sp, #128]
    stp     x18, x19, [sp, #144]
    stp     x20, x21, [sp, #160]
    stp     x22, x23, [sp, #176]
    stp     x24, x25, [sp, #192]
    stp     x26, x27, [sp, #208]
    stp     x28, x29, [sp, #224]
    str     x30, [sp, #240]

    bl      arm64_irq_handler

    ldp     x0, x1, [sp, #0]
    ldp     x2, x3, [sp, #16]
    ldp     x4, x5, [sp, #32]
    ldp     x6, x7, [sp, #48]
    ldp     x8, x9, [sp, #64]
    ldp     x10, x11, [sp, #80]
    ldp     x12, x13, [sp, #96]
    ldp     x14, x15, [sp, #112]
    ldp     x16, x17, [sp, #128]
    ldp     x18, x19, [sp, #144]
    ldp     x20, x21, [sp, #160]
    ldp     x22, x23, [sp, #176]
    ldp     x24, x25, [sp, #192]
    ldp     x26, x27, [sp, #208]
    ldp     x28, x29, [sp, #224]
    ldr     x30, [sp, #240]
    add     sp, sp, #256
    eret

fiq_el1h_sp:
    b       fiq_handler

serr_el1h_sp:
    b       serr_handler

sync_el0_a64:
    /* Handle system calls from EL0 */
    stp     x0, x1, [sp, #-16]!
    stp     x2, x3, [sp, #-16]!
    stp     x4, x5, [sp, #-16]!
    stp     x6, x7, [sp, #-16]!
    stp     x8, x9, [sp, #-16]!
    stp     x10, x11, [sp, #-16]!
    stp     x12, x13, [sp, #-16]!
    stp     x14, x15, [sp, #-16]!
    stp     x16, x17, [sp, #-16]!
    stp     x18, x19, [sp, #-16]!
    stp     x20, x21, [sp, #-16]!
    stp     x22, x23, [sp, #-16]!
    stp     x24, x25, [sp, #-16]!
    stp     x26, x27, [sp, #-16]!
    stp     x28, x29, [sp, #-16]!
    stp     x30, xzr, [sp, #-16]!

    mrs     x0, esr_el1
    mrs     x1, far_el1

    bl      arm64_syscall_handler

    ldp     x30, xzr, [sp], #16
    ldp     x28, x29, [sp], #16
    ldp     x26, x27, [sp], #16
    ldp     x24, x25, [sp], #16
    ldp     x22, x23, [sp], #16
    ldp     x20, x21, [sp], #16
    ldp     x18, x19, [sp], #16
    ldp     x16, x17, [sp], #16
    ldp     x14, x15, [sp], #16
    ldp     x12, x13, [sp], #16
    ldp     x10, x11, [sp], #16
    ldp     x8, x9, [sp], #16
    ldp     x6, x7, [sp], #16
    ldp     x4, x5, [sp], #16
    ldp     x2, x3, [sp], #16
    ldp     x0, x1, [sp], #16
    eret

irq_el0_a64:
    b       irq_handler
fiq_el0_a64:
    b       fiq_handler
serr_el0_a64:
    b       serr_handler

sync_el0_a32:
    b       sync_el0_a64       /* Treat AArch32 as AArch64 for now */
irq_el0_a32:
    b       irq_handler
fiq_el0_a32:
    b       fiq_handler
serr_el0_a32:
    b       serr_handler

/* Default handler stubs */
exception_handler:
    /* Save registers and call C handler */
    mrs     x3, spsr_el1
    stp     x0, x1, [sp, #-16]!
    stp     x2, x3, [sp, #-16]!
    mrs     x0, esr_el1
    mrs     x1, far_el1
    mrs     x2, elr_el1
    bl      arm64_exception_default
    ldp     x2, x3, [sp], #16
    ldp     x0, x1, [sp], #16
    eret

irq_handler:
    /* Save minimal context */
    sub     sp, sp, #16
    str     x30, [sp]
    bl      arm64_irq_default
    ldr     x30, [sp]
    add     sp, sp, #16
    eret

fiq_handler:
    sub     sp, sp, #16
    str     x30, [sp]
    bl      arm64_fiq_default
    ldr     x30, [sp]
    add     sp, sp, #16
    eret

serr_handler:
    sub     sp, sp, #16
    str     x30, [sp]
    bl      arm64_serr_default
    ldr     x30, [sp]
    add     sp, sp, #16
    eret