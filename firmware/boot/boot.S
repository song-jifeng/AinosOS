/*
 * AinosOS - boot/boot.S
 * x86_64 boot entry point with Multiboot2 support
 *
 * This file implements the transition from:
 *   Real mode (GRUB) -> Protected mode (32-bit) -> Long mode (64-bit)
 *
 * It sets up:
 *   - Multiboot2 header
 *   - Page tables for identity mapping (first 4MB + higher half)
 *   - GDT for 64-bit mode
 *   - Stack and transition to C code
 */

#include "multiboot.h"

/* Multiboot2 header must be in the first 32768 bytes of the image */
.section .multiboot, "a"
.align 8

multiboot2_header:
    /* Magic */
    .long   MULTIBOOT2_MAGIC
    /* Architecture: 0 = 32-bit (i386), 4 = 32-bit MIPS */
    .long   0
    /* Header length */
    .long   multiboot2_header_end - multiboot2_header
    /* Checksum */
    .long   -(MULTIBOOT2_MAGIC + 0 + (multiboot2_header_end - multiboot2_header))

    /* --- Tag: Module alignment --- */
    .align 8
    .word   MULTIBOOT2_HEADER_TAG_MODULE_ALIGN
    .word   0
    .long   8

    /* --- Tag: Information request --- */
    .align 8
    .word   MULTIBOOT2_HEADER_TAG_INFORMATION_REQUEST
    .word   0
    .long   10 * 4 + 8  /* size: tag + 10 uint32s */
    .long   1   /* Basic meminfo */
    .long   3   /* Command line */
    .long   4   /* Modules */
    .long   6   /* ELF symbols */
    .long   8   /* Memory map */
    .long   9   /* Boot device */
    .long   14  /* ACPI RSDP v1 */
    .long   15  /* ACPI RSDP v2 */
    .long   17  /* EFI memory map */
    .long   21  /* Load base address */

    /* --- Tag: Framebuffer (request 1024x768x32) --- */
    .align 8
    .word   MULTIBOOT2_HEADER_TAG_FRAMEBUFFER
    .word   0
    .long   20
    .long   1024    /* Width */
    .long   768     /* Height */
    .long   32      /* Depth (bpp) */

    /* --- Tag: Entry address (EFI64) --- */
    .align 8
    .word   MULTIBOOT2_HEADER_TAG_ENTRY_ADDRESS_EFI64
    .word   0
    .long   24
    .quad   _start

    /* --- Tag: Relocatable --- */
    .align 8
    .word   MULTIBOOT2_HEADER_TAG_RELOCATABLE
    .word   0
    .long   24
    .long   0x100000  /* Min addr */
    .long   0xFFFFFFFF /* Max addr */
    .long   4096      /* Align to 4K */
    .long   0         /* Preference: 0 = none, 1 = load high, 2 = load low */

    /* --- End tag --- */
    .align 8
    .word   0   /* type = 0 */
    .word   0
    .long   8

multiboot2_header_end:

/* Page table structures */
.section .bss, "aw", @nobits
.align 4096

/* Level 4 Page Map */
.global pml4
pml4:
    .space 4096

/* Level 3 Page Directory Pointer Table (low 4GB) */
.global pdpt_low
pdpt_low:
    .space 4096

/* Level 3 Page Directory Pointer Table (higher half) */
.global pdpt_high
pdpt_high:
    .space 4096

/* Page Directory (first 2MB page) */
.global pd_low
pd_low:
    .space 4096

/* Temporary stack */
.section .bss
.align 16
boot_stack_bottom:
    .space 16384  /* 16KB temporary stack */
boot_stack_top:

/* Boot info structure */
.section .data
.align 8
.global g_boot_info
g_boot_info:
    .space 128   /* sizeof(boot_info) */

.global g_boot_status
g_boot_status:
    .space 272   /* sizeof(boot_status) */

/* Kernel physical offset for higher-half mapping */
.global _kernel_phys_offset
_kernel_phys_offset:
    .quad 0

/* Protected mode GDT */
.section .data
.align 16
gdt32:
    .quad 0x0000000000000000  /* NULL descriptor */
    .quad 0x00CF9A000000FFFF  /* 32-bit code segment: base=0, limit=4G, DPL=0, code, R/O */
    .quad 0x00CF92000000FFFF  /* 32-bit data segment: base=0, limit=4G, DPL=0, data, R/W */
gdt32_end:

gdt32_ptr:
    .word gdt32_end - gdt32 - 1
    .long gdt32

/* 64-bit GDT (loaded after long mode entry) */
.align 16
gdt64:
    .quad 0x0000000000000000  /* 0x00: NULL descriptor */
    .quad 0x00AF9A000000FFFF  /* 0x08: 64-bit code segment, DPL=0, present */
    .quad 0x00CF92000000FFFF  /* 0x10: 64-bit data segment, DPL=0, present */
    .quad 0x00AFFA000000FFFF  /* 0x18: 64-bit code segment, DPL=3 (user) */
    .quad 0x00CFF2000000FFFF  /* 0x20: 64-bit data segment, DPL=3 (user) */
    .quad 0x00AF9A000000FFFF  /* 0x28: 64-bit TSS (placeholder, will be filled later) */
gdt64_end:

gdt64_ptr:
    .word gdt64_end - gdt64 - 1
    .quad gdt64

/* ------------------------------------------------------------------ */
/* Entry point: _start                                                */
/* ------------------------------------------------------------------ */

.section .text.boot, "ax"
.code32

.global _start
_start:
    /* GRUB loads us in 32-bit protected mode with paging off */
    /* EAX = Multiboot magic, EBX = Multiboot info address */

    /* Save multiboot info */
    movl    %eax, (g_boot_info + 0)   /* magic */
    movl    %ebx, (g_boot_info + 8)   /* mb_info_addr */

    /* Disable interrupts */
    cli

    /* Set up stack (temporary, in lower memory) */
    movl    $boot_stack_top, %esp
    movl    %esp, %ebp

    /* Save boot info pointer for later C code use */
    pushl   %ebx    /* multiboot info */
    pushl   %eax    /* multiboot magic */

    /* Check for CPUID support by toggling ID bit in EFLAGS */
    pushfl
    popl    %eax
    movl    %eax, %ecx
    xorl    $0x200000, %eax   /* Toggle ID bit */
    pushl   %eax
    popfl
    pushfl
    popl    %eax
    pushl   %ecx
    popfl
    cmpl    %eax, %ecx
    je      .Lno_cpuid

    /* Check for extended CPUID (0x80000001) */
    movl    $0x80000000, %eax
    cpuid
    cmpl    $0x80000001, %eax
    jb      .Lno_long_mode

    /* Check for long mode (bit 29 of EDX after CPUID 0x80000001) */
    movl    $0x80000001, %eax
    cpuid
    testl   $(1 << 29), %edx
    jz      .Lno_long_mode

    /* Check for PAE (bit 6 of EDX after CPUID 1) */
    movl    $1, %eax
    cpuid
    testl   $(1 << 6), %edx
    jz      .Lno_pae

    /* Enable PAE and PSE in CR4 */
    movl    %cr4, %eax
    orl     $(1 << 5), %eax    /* PAE */
    orl     $(1 << 4), %eax    /* PSE */
    movl    %eax, %cr4

    /*
     * Set up page tables for identity mapping the first 4MB
     * and a higher-half mapping at 0xFFFF800000000000
     *
     * Page table structure:
     *   PML4[0] -> PDPT_low (identity map low 4MB)
     *   PML4[256] -> PDPT_high (higher half, map at 0xFFFF800000000000)
     *   PDPT_low[0] -> PD_low (2MB pages)
     *   PDPT_high[0] -> PD_low (same physical pages)
     *   PD_low[0] -> 2MB page (0x000000 - 0x200000), R/W, Present, PS
     *   PD_low[1] -> 2MB page (0x200000 - 0x400000), R/W, Present, PS
     */

    /* Clear page tables */
    movl    $pml4, %edi
    xorl    %eax, %eax
    movl    $4096, %ecx
    rep stosb

    movl    $pdpt_low, %edi
    xorl    %eax, %eax
    movl    $4096, %ecx
    rep stosb

    movl    $pdpt_high, %edi
    xorl    %eax, %eax
    movl    $4096, %ecx
    rep stosb

    movl    $pd_low, %edi
    xorl    %eax, %eax
    movl    $4096, %ecx
    rep stosb

    /* Set up PD_low: two 2MB pages for the first 4MB */
    movl    $pd_low, %edi
    movl    $0x000083, %eax   /* Present, R/W, PS (2MB page), address 0x000000 */
    movl    %eax, (%edi)
    movl    $0x000083, %eax   /* address 0x200000 */
    movl    %eax, 8(%edi)

    /* Set up PDPT_low[0] -> PD_low */
    movl    $pd_low, %eax
    orl     $0x03, %eax       /* Present, R/W */
    movl    %eax, (pdpt_low)
    movl    $0, 4(pdpt_low)

    /* Set up PDPT_high[0] -> PD_low (same PD for higher half) */
    movl    $pd_low, %eax
    orl     $0x03, %eax
    movl    %eax, (pdpt_high)
    movl    $0, 4(pdpt_high)

    /* Set up PML4[0] -> PDPT_low */
    movl    $pdpt_low, %eax
    orl     $0x03, %eax
    movl    %eax, (pml4)
    movl    $0, 4(pml4)

    /* Set up PML4[256] -> PDPT_high (higher half) */
    /* PML4 entry 256 = 0xFFFF800000000000 >> 39 & 0x1FF = 256 */
    movl    $pdpt_high, %eax
    orl     $0x03, %eax
    movl    %eax, (pml4 + 256*8)
    movl    $0, 4(pml4 + 256*8)

    /* Load PML4 address into CR3 */
    movl    $pml4, %eax
    movl    %eax, %cr3

    /* Enable Long Mode by setting EFER.LME */
    movl    $0xC0000080, %ecx  /* EFER MSR */
    rdmsr
    orl     $(1 << 8), %eax    /* LME = 1 */
    orl     $(1 << 11), %eax   /* NXE = 1 (NX bit enable) */
    wrmsr

    /* Enable paging (set CR0.PG) */
    movl    %cr0, %eax
    orl     $(1 << 31), %eax   /* PG */
    andl    $~((1 << 30) | (1 << 29)), %eax  /* Clear CD, NW */
    movl    %eax, %cr0

    /* Now we are in 32-bit compatibility mode. Load GDT with 64-bit selector */
    lgdt    (gdt64_ptr)

    /* Far jump to 64-bit mode */
    pushl   $0x08          /* 64-bit code selector */
    pushl   $.L64bit_entry
    retf

.Lno_cpuid:
    /* CPU doesn't support CPUID - halt */
    movl    $0x4F, (0xB8000)  /* Print '!' on screen */
    hlt
    jmp     .Lno_cpuid

.Lno_long_mode:
    /* CPU doesn't support long mode */
    movw    $0x4F21, (0xB8000)  /* Print '!' */
    hlt
    jmp     .Lno_long_mode

.Lno_pae:
    /* CPU doesn't support PAE */
    movw    $0x4F22, (0xB8000)  /* Print '"' */
    hlt
    jmp     .Lno_pae

/* ------------------------------------------------------------------ */
/* 64-bit mode entry point                                            */
/* ------------------------------------------------------------------ */

.code64
.L64bit_entry:
    /* We are now in 64-bit long mode */

    /* Load segment registers with 64-bit data selectors */
    movw    $0x10, %ax   /* 64-bit data segment */
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %fs
    movw    %ax, %gs
    movw    %ax, %ss

    /* Set up RSP (stack) */
    movabs  $boot_stack_top, %rsp
    movq    %rsp, %rbp

    /* Set up kernel_phys_offset for higher-half calculations */
    /* We are running with identity mapping, so phys = virt at low addresses */
    /* Higher half base = 0xFFFF800000000000 */
    movabs  $0xFFFF800000000000, %rax
    movabs  $_kernel_phys_offset, %rcx
    subq    %rax, %rcx
    neg     %rcx
    movabs  $_kernel_phys_offset, %rdx
    movq    %rcx, (%rdx)   /* phys_offset = 0xFFFF800000000000 - 0 = -(higher_half_base) */

    /* Now call the C entry point */
    /* Arguments: magic (EDI), multiboot_info_addr (ESI) */
    movl    (g_boot_info), %edi
    movq    (g_boot_info + 8), %rsi

    /* Align stack to 16 bytes */
    andq    $~15, %rsp

    /* Call kmain (the C entry point) */
    movabs  $kmain, %rax
    call    *%rax

    /* Should never return */
.Lhalt:
    hlt
    jmp     .Lhalt

/*
 * AP (Application Processor) trampoline for SMP boot
 * This is copied to low memory (< 1MB) for AP startup
 */
.section .text.ap_trampoline, "ax", @progbits
.align 16
.code16

.global ap_trampoline_start
.global ap_trampoline_end
.global ap_trampoline_pml4
.global ap_trampoline_stack
.global ap_trampoline_entry

ap_trampoline_start:
    /* Real mode trampoline for AP startup */
    cli
    cld

    /* Enable A20 gate */
    inb     $0x92, %al
    orb     $0x02, %al
    outb    %al, $0x92

    /* Set up GDT for protected mode transition */
    lgdtw   (ap_gdt_ptr - ap_trampoline_start)

    /* Enable protected mode */
    movl    %cr0, %eax
    orl     $0x01, %eax
    movl    %eax, %cr0

    /* Far jump to 32-bit protected mode */
    ljmp    $0x08, $ap_32bit - ap_trampoline_start + 0x7000

.code32
ap_32bit:
    /* Set up data segments */
    movw    $0x10, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %fs
    movw    %ax, %gs
    movw    %ax, %ss

    /* Set up page tables (use BSP's PML4) */
    movl    (ap_trampoline_pml4 - ap_trampoline_start + 0x7000), %eax
    movl    %eax, %cr3

    /* Enable PAE */
    movl    %cr4, %eax
    orl     $(1 << 5), %eax
    movl    %eax, %cr4

    /* Enable long mode */
    movl    $0xC0000080, %ecx
    rdmsr
    orl     $(1 << 8), %eax
    wrmsr

    /* Enable paging */
    movl    %cr0, %eax
    orl     $(1 << 31), %eax
    movl    %eax, %cr0

    /* Load 64-bit GDT */
    lgdt    (ap_gdt64_ptr - ap_trampoline_start + 0x7000)

    /* Jump to 64-bit */
    pushl   $0x08
    pushl   $ap_64bit - ap_trampoline_start + 0x7000
    lret

.code64
ap_64bit:
    movw    $0x10, %ax
    movw    %ax, %ds
    movw    %ax, %es
    movw    %ax, %fs
    movw    %ax, %gs
    movw    %ax, %ss

    /* Load AP stack */
    movabs  $ap_trampoline_stack, %rax
    movq    (%rax), %rsp
    movq    %rsp, %rbp

    /* Load AP entry point */
    movabs  $ap_trampoline_entry, %rax
    movq    (%rax), %rax
    call    *%rax

.Lap_halt:
    hlt
    jmp     .Lap_halt

/* AP trampoline GDTs */
.align 16
ap_gdt:
    .quad 0x0000000000000000
    .quad 0x00CF9A000000FFFF  /* 32-bit code */
    .quad 0x00CF92000000FFFF  /* 32-bit data */
ap_gdt_end:

ap_gdt_ptr:
    .word ap_gdt_end - ap_gdt - 1
    .long ap_gdt - ap_trampoline_start + 0x7000

.align 16
ap_gdt64:
    .quad 0x0000000000000000
    .quad 0x00AF9A000000FFFF  /* 64-bit code */
    .quad 0x00CF92000000FFFF  /* 64-bit data */
ap_gdt64_end:

ap_gdt64_ptr:
    .word ap_gdt64_end - ap_gdt64 - 1
    .quad ap_gdt64 - ap_trampoline_start + 0x7000

/* AP trampoline variables (filled by SMP code) */
.align 8
ap_trampoline_pml4:
    .quad 0
ap_trampoline_stack:
    .quad 0
ap_trampoline_entry:
    .quad 0

ap_trampoline_end: