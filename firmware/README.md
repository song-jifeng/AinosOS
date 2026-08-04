# AinosOS Firmware

AinosOS is a lightweight firmware/bootloader for x86_64 and ARM64 architectures, designed as a minimal operating system foundation.

## Features

- **Multiboot2 compliant** - Bootable by GRUB2 and other Multiboot2-compliant bootloaders
- **x86_64 Long Mode** - Full 64-bit mode with 4-level paging
- **ARM64 AArch64** - Support for ARMv8-A 64-bit architecture
- **SMP** - Symmetric multiprocessing support
- **ACPI** - Advanced Configuration and Power Interface parsing
- **APIC/x2APIC** - Local and I/O APIC support
- **Drivers** - UART, PIT/HPET timers, PS/2 keyboard, PCI enumeration, NVMe, AHCI/SATA, USB, framebuffer
- **VFS** - Virtual File System with TAR filesystem support (initrd)
- **Memory Management** - Physical page frame allocator with bitmap
- **C Library** - String, printf, bitmap, math, CRC32, linked list, hash table

## Directory Structure

```
firmware/
├── boot/           # Bootloader code (x86_64)
│   ├── boot.S      # Assembly entry point
│   ├── boot.h      # Boot header
│   ├── multiboot.h # Multiboot2 definitions
│   ├── gdt.c       # GDT setup
│   ├── idt.c       # IDT setup
│   ├── paging.c    # Page table management
│   ├── memory.c    # Memory detection
│   ├── console.c   # Early console output
│   ├── cpu.c       # CPU detection (CPUID)
│   ├── apic.c      # APIC initialization
│   ├── smp.c       # SMP boot
│   └── acpi.c      # ACPI table parsing
├── arch/           # Architecture-specific code
│   ├── x86_64/     # x86_64 headers and utilities
│   └── arm64/      # ARM64 startup, vectors, MMU
├── drivers/        # Device drivers
│   ├── uart.c      # UART serial driver
│   ├── timer.c     # Timer driver (PIT/HPET)
│   ├── keyboard.c  # PS/2 keyboard driver
│   ├── pci.c       # PCI enumeration
│   ├── nvme.c      # NVMe SSD driver
│   ├── ahci.c      # AHCI/SATA driver
│   ├── usb.c       # USB controller driver
│   └── framebuffer.c # Framebuffer graphics driver
├── lib/            # Standard library
│   ├── string.c    # String and memory functions
│   ├── printf.c    # Formatted output
│   ├── bitmap.c    # Bitmap operations
│   ├── list.h      # Linked list (header-only)
│   ├── hash.h      # Hash table (header-only)
│   ├── crc32.c     # CRC32 checksum
│   └── math.c      # Math utilities
├── fs/             # File system
│   ├── vfs.c       # Virtual File System
│   └── tar.c       # TAR filesystem (initrd)
├── include/        # Common headers
│   ├── types.h     # Type definitions
│   ├── macros.h    # Utility macros
│   ├── errno.h     # Error codes
│   └── compiler.h  # Compiler attributes
├── tests/          # Unit tests
│   ├── test_string.c
│   ├── test_bitmap.c
│   ├── test_list.c
│   └── test_printf.c
├── Makefile        # Build system
├── linker.ld       # Linker script
├── grub.cfg        # GRUB configuration
└── README.md       # This file
```

## Building

### Prerequisites

- GCC cross-compiler (x86_64-elf or aarch64-elf)
- GNU Make
- GRUB2 tools (for ISO creation)
- QEMU (for testing)

### Build for x86_64

```bash
make ARCH=x86_64
```

### Build for ARM64

```bash
make ARCH=arm64
```

### Create bootable ISO

```bash
make iso
```

### Run in QEMU

```bash
make qemu
```

### Run tests

```bash
make test
```

## Boot Process (x86_64)

1. **GRUB** loads the kernel and transfers control to `_start`
2. **boot.S** sets up protected mode, detects CPUID and long mode support
3. **Page tables** are created for identity mapping and higher-half mapping
4. **Long mode** is enabled via EFER MSR
5. **GDT** is loaded with 64-bit code/data segments
6. **C code** takes over in `kmain()`
7. **Console** initialization (VGA text mode + serial)
8. **Memory detection** from Multiboot2 memory map
9. **CPU detection** via CPUID
10. **GDT/IDT** initialization
11. **Paging** full initialization
12. **APIC** initialization
13. **ACPI** table parsing
14. **SMP** bring-up of Application Processors
15. **Driver** initialization
16. **VFS** and **filesystem** mounting
17. System ready

## Memory Map (x86_64)

| Region | Address | Description |
|--------|---------|-------------|
| Low Memory | 0x00000000 - 0x0009FC00 | Usable (640KB) |
| EBDA | 0x0009FC00 - 0x000A0000 | Extended BIOS Data Area |
| Video RAM | 0x000A0000 - 0x000C0000 | VGA framebuffer |
| Option ROMs | 0x000C0000 - 0x00100000 | Expansion ROMs |
| Kernel | 0x00100000+ | Kernel loaded at 1MB |
| Higher Half | 0xFFFF800000000000 | Kernel virtual address space |

## License

This is a firmware project for educational purposes.