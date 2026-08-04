#
# AinosOS Firmware Makefile
# Build system for x86_64 and ARM64 targets
#

# Toolchain configuration
CC              = gcc
LD              = ld
AS              = gcc
AR              = ar
OBJCOPY         = objcopy
OBJDUMP         = objdump
NM              = nm
SIZE            = size
GRUB_MKRESCUE   = grub-mkrescue
QEMU            = qemu-system-x86_64

# Architecture (default: x86_64)
ARCH           ?= x86_64

# Target-specific settings
ifeq ($(ARCH), x86_64)
    CFLAGS_ARCH  = -m64 -mno-red-zone -mno-mmx -mno-sse -mno-sse2 -mno-80387
    CFLAGS_ARCH += -mcmodel=kernel -mno-fp-ret-in-387
    ASFLAGS_ARCH = --64
    LDFLAGS_ARCH = -m elf_x86_64
    TARGET        = ainos-x86_64.bin
    QEMU_ARCH    = -cpu qemu64,+apic,+x2apic,+fsgsbase,+rdrand
    QEMU_ARCH    += -machine q35
else ifeq ($(ARCH), arm64)
    CCFLAGS_ARCH  = -march=armv8-a -mtune=cortex-a72
    ASFLAGS_ARCH  = -march=armv8-a
    LDFLAGS_ARCH  = -m aarch64elf
    TARGET        = ainos-aarch64.elf
    QEMU_ARCH    = -machine virt -cpu cortex-a72
    QEMU          = qemu-system-aarch64
endif

# Base CFLAGS
CFLAGS          = -ffreestanding -nostdlib -nostdinc -fno-builtin -fno-stack-protector
CFLAGS         += -fno-omit-frame-pointer -fno-pic -fno-pie -fno-asynchronous-unwind-tables
CFLAGS         += -Wall -Wextra -Werror -Wno-unused-parameter -Wno-unused-function
CFLAGS         += -Wno-address-of-packed-member
CFLAGS         += -I. -Iinclude -Iarch/$(ARCH)
CFLAGS         += $(CFLAGS_ARCH)
CFLAGS         += -O2 -g

# Safe CFLAGS for testing
CFLAGS_TEST     = -ffreestanding -I. -Iinclude -Iarch/$(ARCH)
CFLAGS_TEST    += -Wall -Wextra -Wno-unused-parameter -Wno-unused-function
CFLAGS_TEST    += -O2 -g

# Assembly flags
ASFLAGS         = -ffreestanding -nostdlib -nostdinc -I. -Iinclude
ASFLAGS         = $(ASFLAGS_ARCH) -I. -Iinclude
ASFLAGS         += -x assembler-with-cpp

# Linker flags
LDFLAGS         = -ffreestanding -nostdlib -static -z max-page-size=0x1000
LDFLAGS        += $(LDFLAGS_ARCH)
LDFLAGS        += -T linker.ld

# Source files
C_SOURCES  = $(wildcard boot/*.c)
C_SOURCES += $(wildcard lib/*.c)
C_SOURCES += $(wildcard drivers/*.c)
C_SOURCES += $(wildcard fs/*.c)

# Architecture-specific sources
ifeq ($(ARCH), x86_64)
    ASM_SOURCES  = boot/boot.S
    C_SOURCES   += $(wildcard arch/x86_64/*.c)
else ifeq ($(ARCH), arm64)
    ASM_SOURCES  = arch/arm64/startup.S arch/arm64/vectors.S
    C_SOURCES   += $(wildcard arch/arm64/*.c)
endif

# Test sources
TEST_SOURCES = $(wildcard tests/*.c)

# Object files
OBJS  = $(C_SOURCES:.c=.o)
OBJS += $(ASM_SOURCES:.S=.o)

# Test objects
TEST_OBJS = $(TEST_SOURCES:.c=.o)

# Dependency files
DEPS = $(OBJS:.o=.d) $(TEST_OBJS:.o=.d)

# Default target
all: $(TARGET)

# Include dependency files
-include $(DEPS)

# Link the kernel
$(TARGET): $(OBJS) linker.ld
	@echo "  LD      $@"
	$(CC) $(LDFLAGS) -o $@ $(OBJS)
	@echo "  Kernel size:"
	$(SIZE) $@

# Compile C files
%.o: %.c
	@echo "  CC      $<"
	$(CC) $(CFLAGS) -MMD -c -o $@ $<

# Compile assembly files
%.o: %.S
	@echo "  AS      $<"
	$(CC) $(ASFLAGS) -MMD -c -o $@ $<

# Create ISO image for GRUB boot
iso: $(TARGET) grub.cfg
	@echo "  ISO     ainos.iso"
	@mkdir -p iso/boot/grub
	@cp $(TARGET) iso/boot/
	@cp grub.cfg iso/boot/grub/
	$(GRUB_MKRESCUE) -o ainos.iso iso
	@rm -rf iso

# Run in QEMU
qemu: $(TARGET)
	@echo "  QEMU    $<"
	$(QEMU) $(QEMU_ARCH) -m 512M -cdrom ainos.iso -serial stdio -vga std

# Run in QEMU with debug
qemu-debug: $(TARGET)
	@echo "  QEMU    $< (debug)"
	$(QEMU) $(QEMU_ARCH) -m 512M -cdrom ainos.iso -serial stdio -vga std \
		-s -S -d int,cpu_reset

# Build test binary
test: $(TEST_OBJS) lib/string.o lib/printf.o lib/bitmap.o
	@echo "  LD      ainos-test"
	$(CC) -ffreestanding -nostdlib -static -g -o ainos-test \
		$(TEST_OBJS) lib/string.o lib/printf.o lib/bitmap.o \
		-lc -lgcc
	@echo "  Running tests..."
	./ainos-test

# Run individual tests
test-string: tests/test_string.o lib/string.o lib/printf.o
	$(CC) -ffreestanding -g -o test-string $^ -lc -lgcc
	./test-string

test-bitmap: tests/test_bitmap.o lib/bitmap.o lib/printf.o lib/string.o
	$(CC) -ffreestanding -g -o test-bitmap $^ -lc -lgcc
	./test-bitmap

test-list: tests/test_list.o lib/printf.o lib/string.o
	$(CC) -ffreestanding -g -o test-list $^ -lc -lgcc
	./test-list

test-printf: tests/test_printf.o lib/printf.o lib/string.o
	$(CC) -ffreestanding -g -o test-printf $^ -lc -lgcc
	./test-printf

# Generate disassembly
disasm: $(TARGET)
	@echo "  OBJDUMP $<"
	$(OBJDUMP) -d $(TARGET) > ainos.dis

# Generate symbol map
sym: $(TARGET)
	@echo "  NM      $<"
	$(NM) $(TARGET) | sort > ainos.sym

# Show kernel size
size: $(TARGET)
	$(SIZE) $(TARGET)
	$(OBJDUMP) -h $(TARGET)

# Clean build artifacts
clean:
	@echo "  CLEAN"
	@rm -f $(OBJS) $(DEPS) $(TEST_OBJS)
	@rm -f $(TARGET) ainos-test ainos.iso ainos.dis ainos.sym
	@rm -f test-string test-bitmap test-list test-printf
	@rm -rf iso

# Phony targets
.PHONY: all iso qemu qemu-debug test clean disasm sym size
.PHONY: test-string test-bitmap test-list test-printf

# Print build configuration
config:
	@echo "Build configuration:"
	@echo "  ARCH:     $(ARCH)"
	@echo "  CC:       $(CC)"
	@echo "  CFLAGS:   $(CFLAGS)"
	@echo "  Target:   $(TARGET)"
	@echo "  Sources:  $(C_SOURCES)"
	@echo "  ASM:      $(ASM_SOURCES)"
	@echo "  Objects:  $(OBJS)"

# Help
help:
	@echo "AinosOS Build System"
	@echo "===================="
	@echo "Targets:"
	@echo "  all          - Build the kernel (default)"
	@echo "  iso          - Create GRUB bootable ISO"
	@echo "  qemu         - Run in QEMU"
	@echo "  qemu-debug   - Run in QEMU with debug"
	@echo "  test         - Run all tests"
	@echo "  clean        - Clean build artifacts"
	@echo "  disasm       - Generate disassembly"
	@echo "  sym          - Generate symbol map"
	@echo "  size         - Show kernel section sizes"
	@echo "  config       - Show build configuration"
	@echo "  help         - Show this help"
	@echo ""
	@echo "Variables:"
	@echo "  ARCH=x86_64  - Build for x86_64 (default)"
	@echo "  ARCH=arm64   - Build for ARM64"
	@echo ""
	@echo "Examples:"
	@echo "  make             - Build x86_64 kernel"
	@echo "  make iso         - Create bootable ISO"
	@echo "  make qemu        - Run in QEMU"
	@echo "  make ARCH=arm64  - Build ARM64 kernel"