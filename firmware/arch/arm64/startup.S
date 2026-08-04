/*
 * AinosOS - arch/arm64/startup.S
 * AArch64 startup code
 */

.section .text.boot, "ax"
.global _start
.global _start_el2
.global _start_el1

/* Exception levels */
#define EL2 2
#define EL1 1

_start:
    /* Check exception level and drop to EL1 if needed */
    mrs     x0, current_el
    lsr     x0, x0, #2
    cmp     x0, #EL2
    b.eq    _start_el2
    cmp     x0, #EL1
    b.eq    _start_el1
    /* EL3 not supported, halt */
    b       halt_el3

_start_el2:
    /* We are in EL2 (hypervisor mode, typical for 64-bit ARM) */
    /* Set up EL2 own page tables or switch to EL1 */

    /* Configure CNTVOFF_EL2 to 0 */
    msr     cntvoff_el2, xzr

    /* Set up HCR_EL2 to enable AArch64 at EL1 */
    mov     x0, #(1 << 31)      /* RW: AArch64 at EL1 */
    msr     hcr_el2, x0

    /* Set SCTLR_EL2 to known state */
    mov     x0, #0x30C50838
    msr     sctlr_el2, x0

    /* Set up generic timer frequency */
    mrs     x0, cntfrq_el0
    msr     cntfrq_el0, x0

    /* Set up SPSR_EL2 for EL1h mode */
    mov     x0, #0x3C5           /* All interrupts masked, EL1h */
    msr     spsr_el2, x0

    /* Set up EL1 entry point */
    adr     x0, _start_el1
    msr     elr_el2, x0

    /* Return to EL1 */
    eret

_start_el1:
    /* We are in EL1 (kernel mode) */

    /* Set up stack */
    ldr     x0, =_stack_top
    mov     sp, x0

    /* Clear BSS */
    ldr     x0, =_bss_start
    ldr     x1, =_bss_end
    mov     x2, #0
bss_clear:
    str     x2, [x0], #8
    cmp     x0, x1
    b.lo    bss_clear

    /* Set up exception vectors */
    ldr     x0, =exception_vector_table
    msr     vbar_el1, x0
    isb

    /* Set up MMU (page tables) */
    bl      mmu_init

    /* Enable FP/SIMD */
    mov     x0, #(3 << 20)       /* CPACR_EL1.FPEN */
    msr     cpacr_el1, x0
    isb

    /* Enable I-cache and D-cache */
    mrs     x0, sctlr_el1
    orr     x0, x0, #(1 << 2)    /* C - D-cache */
    orr     x0, x0, #(1 << 12)   /* I - I-cache */
    msr     sctlr_el1, x0
    isb

    /* Enable interrupts */
    msr     daifclr, #0xF       /* Clear all interrupt masks */

    /* Call kernel main */
    bl      kmain

    /* Should not return */
halt_loop:
    wfi
    b       halt_loop

halt_el3:
    /* EL3 not supported */
    wfi
    b       halt_el3

/* Secondary CPU entry point */
.global _secondary_start
_secondary_start:
    /* Set up stack for secondary CPU */
    ldr     x0, =_secondary_stack
    mov     sp, x0

    /* Enable FP/SIMD */
    mov     x0, #(3 << 20)
    msr     cpacr_el1, x0
    isb

    /* Enable caches */
    mrs     x0, sctlr_el1
    orr     x0, x0, #(1 << 2)
    orr     x0, x0, #(1 << 12)
    msr     sctlr_el1, x0
    isb

    /* Enable interrupts */
    msr     daifclr, #0xF

    /* Call secondary CPU init */
    bl      secondary_cpu_init

    /* Should not return */
    wfi
    b       halt_loop

/* Data section */
.section .data
.align 3
.global _kernel_phys_offset
_kernel_phys_offset:
    .quad 0

/* Stack */
.section .bss
.align 16
_stack_bottom:
    .space 32768   /* 32KB stack */
_stack_top:

_secondary_stack:
    .space 8192    /* Secondary CPU stack */
_secondary_stack_top: