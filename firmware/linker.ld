/*
 * AinosOS - linker.ld
 * Main linker script for x86_64 kernel
 */

OUTPUT_FORMAT(elf64-x86-64)
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)

/* Kernel load address (physical) */
KERNEL_PHYS_BASE = 0x00100000;
KERNEL_VIRT_BASE = 0xFFFF800000000000;

PHDRS
{
    headers PT_PHDR PHDRS;
    text    PT_LOAD FLAGS(5);  /* PF_R | PF_X */
    rodata  PT_LOAD FLAGS(4);  /* PF_R */
    data    PT_LOAD FLAGS(6);  /* PF_R | PF_W */
    bss     PT_LOAD FLAGS(6);  /* PF_R | PF_W */
}

SECTIONS
{
    /* Start at 1MB physical (identity mapped) */
    . = KERNEL_PHYS_BASE;

    . = ALIGN(4096);
    _kernel_start = .;

    /* Multiboot header must be in first 32KB */
    .multiboot : {
        *(.multiboot)
        . = ALIGN(8);
    } :text

    . += KERNEL_VIRT_BASE;

    /* Text section */
    .text KERNEL_VIRT_BASE + KERNEL_PHYS_BASE + SIZEOF(.multiboot) : AT(ADDR(.text) - KERNEL_VIRT_BASE) {
        _text_start = .;
        *(.text.boot)
        *(.text.ap_trampoline)
        *(.text)
        *(.text.*)
        . = ALIGN(4096);
        _text_end = .;
    } :text

    /* Read-only data */
    .rodata : AT(ADDR(.rodata) - KERNEL_VIRT_BASE) {
        _rodata_start = .;
        *(.rodata)
        *(.rodata.*)
        *(.got)
        *(.got.plt)
        . = ALIGN(4096);
        _rodata_end = .;
    } :rodata

    /* Initcall section */
    .initcall : AT(ADDR(.initcall) - KERNEL_VIRT_BASE) {
        _initcall_start = .;
        *(.initcall.*)
        . = ALIGN(8);
        _initcall_end = .;
    } :rodata

    /* Data section */
    .data : AT(ADDR(.data) - KERNEL_VIRT_BASE) {
        _data_start = .;
        *(.data)
        *(.data.*)
        . = ALIGN(4096);
        _data_end = .;
    } :data

    /* BSS section (zero-initialized) */
    .bss : AT(ADDR(.bss) - KERNEL_VIRT_BASE) {
        _bss_start = .;
        *(.bss)
        *(.bss.*)
        *(COMMON)
        . = ALIGN(4096);
        _bss_end = .;
    } :bss

    /* Page tables must be page-aligned */
    .page_tables : AT(ADDR(.page_tables) - KERNEL_VIRT_BASE) {
        *(.page_tables)
        . = ALIGN(4096);
    } :bss

    /* Discard unnecessary sections */
    /DISCARD/ : {
        *(.comment)
        *(.note.*)
        *(.debug*)
        *(.eh_frame)
        *(.eh_frame_hdr)
        *(.gcc_except_table)
    }

    _kernel_end = .;
    _kernel_size = _kernel_end - _kernel_start;

    /* Kernel offsets for page table setup */
    _kernel_phys_start = KERNEL_PHYS_BASE;
    _kernel_virt_start = KERNEL_VIRT_BASE;

    /* BSS size */
    _bss_size = _bss_end - _bss_start;
}