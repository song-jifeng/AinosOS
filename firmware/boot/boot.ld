/*
 * AinosOS - boot/boot.ld
 * Linker script for the boot stage (pre-kernel)
 *
 * This script is used if the boot stage is a separate binary.
 * The main linker script is at the project root (linker.ld).
 */

OUTPUT_FORMAT(elf64-x86-64)
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)

SECTIONS
{
    /* Boot code loaded at 1MB by GRUB */
    . = 0x100000;

    .multiboot : {
        *(.multiboot)
    }

    .text : {
        *(.text.boot)
        *(.text)
        *(.text.*)
    }

    .rodata : {
        *(.rodata)
        *(.rodata.*)
    }

    .data : {
        *(.data)
        *(.data.*)
        *(.got)
        *(.got.plt)
    }

    .bss : {
        *(.bss)
        *(.bss.*)
        *(COMMON)
    }

    /* Discard unnecessary sections */
    /DISCARD/ : {
        *(.comment)
        *(.note.*)
        *(.debug*)
        *(.eh_frame)
        *(.eh_frame_hdr)
    }
}