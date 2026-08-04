# SPDX-License-Identifier: GPL-2.0
#
# Ainos OS - Architecture-specific SIMD build rules
# ==================================================
# This Makefile is included from the main kernel Makefile.
# It provides conditional compilation for x86 and ARM64 SIMD
# acceleration modules.
#
# Usage:
#   ARCH=x86_64  -> builds x86 AVX2, AVX-512, AMX implementations
#   ARCH=arm64   -> builds ARM64 NEON, SVE, SVE2 implementations
#
# For out-of-tree builds, pass ARCH=<arch> to the make command.

# ============================================
# x86 SIMD Objects
# ============================================
ifneq ($(filter x86_64 i386 i686,$(ARCH)),)
  # Always include the base registration object
  ai-vector-accel-objs += arch/x86/avx2_impl.o
  ai-vector-accel-objs += arch/x86/avx512_impl.o
  ai-vector-accel-objs += arch/x86/amx_impl.o
  ai-vector-accel-objs += arch/x86/simd_benchmark.o

  # x86-specific compile flags:
  # AVX2 - enable AVX2, FMA, and AVX code generation
  # AVX-512 - enable AVX-512 Foundation, BW, DQ, and VL
  # AMX - enable Intel AMX TILE extensions
  #
  # We use per-function attributes, so we only need basic
  # x86 intrinsic support at the file level.
  ccflags-$(CONFIG_X86) += -mavx2 -mfma -mavx512f -mavx512bw
  ccflags-$(CONFIG_X86) += -mavx512dq -mavx512vl
  ccflags-$(CONFIG_X86) += -mamx-tile -mamx-int8 -mamx-bf16
  ccflags-$(CONFIG_X86) += -mprefetchwt1 -mno-avx512pf
  ccflags-$(CONFIG_X86) += -ffp-contract=fast

  # Compiler support detection
  # If the compiler doesn't support AMX, we can still build
  # the other files; the AMX file will be excluded.
  ifeq ($(shell echo "int main(){return 0;}" | \
        $(CC) -mamx-tile -x c - -o /dev/null 2>/dev/null; echo $$?),0)
    $(info "Ainos: Compiler supports AMX TILE instructions")
  else
    $(warning "Ainos: Compiler does not support AMX TILE, building without AMX")
    ai-vector-accel-objs := $(filter-out arch/x86/amx_impl.o,$(ai-vector-accel-objs))
  endif

  # Check for AVX-512 support
  ifeq ($(shell echo "int main(){return 0;}" | \
        $(CC) -mavx512f -x c - -o /dev/null 2>/dev/null; echo $$?),0)
    $(info "Ainos: Compiler supports AVX-512 instructions")
  else
    $(warning "Ainos: Compiler does not support AVX-512, building without AVX-512")
    ai-vector-accel-objs := $(filter-out arch/x86/avx512_impl.o,$(ai-vector-accel-objs))
  endif

  # Include path for architecture headers
  ccflags-$(CONFIG_X86) += -I$(PWD)/arch/x86

# ============================================
# ARM64 SIMD Objects
# ============================================
else ifneq ($(filter arm64 aarch64,$(ARCH)),)
  ai-vector-accel-objs += arch/arm64/neon_impl.o
  ai-vector-accel-objs += arch/arm64/sve_impl.o

  # ARM64 always has NEON, but SVE requires compiler support
  # NEON is enabled by default on ARM64 Linux
  ifeq ($(shell echo "int main(){return 0;}" | \
        $(CC) -march=armv8-a+sve -x c - -o /dev/null 2>/dev/null; echo $$?),0)
    $(info "Ainos: Compiler supports SVE instructions")
    ccflags-$(CONFIG_ARM64) += -march=armv8-a+sve+sve2
  else
    $(warning "Ainos: Compiler does not support SVE, building without SVE")
    ai-vector-accel-objs := $(filter-out arch/arm64/sve_impl.o,$(ai-vector-accel-objs))
    ccflags-$(CONFIG_ARM64) += -march=armv8-a
  endif

  ccflags-$(CONFIG_ARM64) += -I$(PWD)/arch/arm64

# ============================================
# Fallback for other architectures
# ============================================
else
  # No SIMD acceleration for this architecture
  # The generic C implementation will be used
  $(info "Ainos: No SIMD acceleration available for architecture '$(ARCH)'")
endif

# ============================================
# Common build rules for arch files
# ============================================

# Define build targets explicitly
$(obj)/arch/x86/avx2_impl.o: $(src)/arch/x86/avx2_impl.c
	$(call if_changed,cc_o_c)

$(obj)/arch/x86/avx512_impl.o: $(src)/arch/x86/avx512_impl.c
	$(call if_changed,cc_o_c)

$(obj)/arch/x86/amx_impl.o: $(src)/arch/x86/amx_impl.c
	$(call if_changed,cc_o_c)

$(obj)/arch/x86/simd_benchmark.o: $(src)/arch/x86/simd_benchmark.c
	$(call if_changed,cc_o_c)

$(obj)/arch/arm64/neon_impl.o: $(src)/arch/arm64/neon_impl.c
	$(call if_changed,cc_o_c)

$(obj)/arch/arm64/sve_impl.o: $(src)/arch/arm64/sve_impl.c
	$(call if_changed,cc_o_c)

# ============================================
# Cleanup
# ============================================
clean-files += arch/x86/*.o arch/x86/.*.cmd
clean-files += arch/arm64/*.o arch/arm64/.*.cmd
clean-files += arch/x86/*.ko arch/arm64/*.ko