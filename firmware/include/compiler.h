/*
 * AinosOS - compiler.h
 * Compiler-specific macros, attributes, and builtins
 */

#ifndef AINOS_COMPILER_H
#define AINOS_COMPILER_H

/* Compiler detection */
#if defined(__clang__)
#  define COMPILER_CLANG    1
#  define COMPILER_GCC      0
#  define COMPILER_MSVC     0
#elif defined(__GNUC__) || defined(__GNUG__)
#  define COMPILER_CLANG    0
#  define COMPILER_GCC      1
#  define COMPILER_MSVC     0
#elif defined(_MSC_VER)
#  define COMPILER_CLANG    0
#  define COMPILER_GCC      0
#  define COMPILER_MSVC     1
#else
#  define COMPILER_CLANG    0
#  define COMPILER_GCC      0
#  define COMPILER_MSVC     0
#endif

/* Architecture detection */
#if defined(__x86_64__) || defined(__amd64__)
#  define ARCH_X86_64       1
#  define ARCH_ARM64        0
#elif defined(__aarch64__)
#  define ARCH_X86_64       0
#  define ARCH_ARM64        1
#else
#  error "Unsupported architecture"
#endif

/* Inline assembly macros */
#if COMPILER_GCC || COMPILER_CLANG
#  define ASM __asm__
#  define ASM_VOLATILE __asm__ volatile
#else
#  define ASM __asm
#  define ASM_VOLATILE __asm volatile
#endif

/* Optimization hints */
#if COMPILER_GCC || COMPILER_CLANG
#  define LIKELY(x)         __builtin_expect(!!(x), 1)
#  define UNLIKELY(x)       __builtin_expect(!!(x), 0)
#  define UNREACHABLE()     __builtin_unreachable()
#  define EXPECT(x, c)      __builtin_expect((x), (c))
#else
#  define LIKELY(x)         (x)
#  define UNLIKELY(x)       (x)
#  define UNREACHABLE()     ((void)0)
#  define EXPECT(x, c)      (x)
#endif

/* Prefetch hints */
#if COMPILER_GCC || COMPILER_CLANG
#  define PREFETCH_RD(addr) __builtin_prefetch((addr), 0, 3)
#  define PREFETCH_WR(addr) __builtin_prefetch((addr), 1, 3)
#else
#  define PREFETCH_RD(addr) ((void)(addr))
#  define PREFETCH_WR(addr) ((void)(addr))
#endif

/* Alignment hints */
#if COMPILER_GCC || COMPILER_CLANG
#  define ASSUME_ALIGNED(ptr, align) __builtin_assume_aligned((ptr), (align))
#else
#  define ASSUME_ALIGNED(ptr, align) (ptr)
#endif

/* Expect integer to be in range */
#if COMPILER_CLANG
#  define ASSUME_IN_RANGE(v, lo, hi) __builtin_assume((v) >= (lo) && (v) <= (hi))
#else
#  define ASSUME_IN_RANGE(v, lo, hi) ((void)0)
#endif

/* Trap / halt */
#if COMPILER_GCC || COMPILER_CLANG
#  define TRAP()            __builtin_trap()
#else
#  define TRAP()            ((void)0)
#endif

/* Debug breakpoint */
#if ARCH_X86_64
#  define BREAKPOINT()      ASM_VOLATILE("int3")
#elif ARCH_ARM64
#  define BREAKPOINT()      ASM_VOLATILE("brk #0")
#else
#  define BREAKPOINT()      ((void)0)
#endif

/* Halt CPU */
#if ARCH_X86_64
#  define HALT()            ASM_VOLATILE("hlt")
#elif ARCH_ARM64
#  define HALT()            ASM_VOLATILE("wfi")
#else
#  define HALT()            ((void)0)
#endif

/* Function and variable annotations */
#define EXPORT              __attribute__((visibility("default")))
#define HIDDEN              __attribute__((visibility("hidden")))
#define WEAK                __attribute__((weak))
#define USED                __attribute__((used))
#define UNUSED              __attribute__((unused))
#define PACKED              __attribute__((packed))
#define ALIGNED(n)          __attribute__((aligned(n)))
#define SECTION(s)          __attribute__((section(s)))
#define NORETURN            __attribute__((noreturn))
#define NOINLINE            __attribute__((noinline))
#define ALWAYS_INLINE       __attribute__((always_inline))
#define WARN_UNUSED         __attribute__((warn_unused_result))
#define DEPRECATED          __attribute__((deprecated))
#define WEAK_DEFAULT        __attribute__((weak, default))

/* Constructor / Destructor */
#define CONSTRUCTOR         __attribute__((constructor))
#define DESTRUCTOR          __attribute__((destructor))

/* Initcall priorities */
#define INITCALL_PRIO(prio) __attribute__((section(".initcall." #prio)))
#define EARLY_INIT          INITCALL_PRIO(0)
#define CORE_INIT           INITCALL_PRIO(1)
#define ARCH_INIT           INITCALL_PRIO(2)
#define SUBSYS_INIT         INITCALL_PRIO(3)
#define DRIVER_INIT         INITCALL_PRIO(4)
#define LATE_INIT           INITCALL_PRIO(5)

/* Thread-local storage */
#if COMPILER_GCC || COMPILER_CLANG
#  define THREAD_LOCAL      __thread
#else
#  define THREAD_LOCAL      __declspec(thread)
#endif

/* printf format checking */
#if COMPILER_GCC || COMPILER_CLANG
#  define PRINTF_FMT(fmt, args) __attribute__((format(printf, fmt, args)))
#else
#  define PRINTF_FMT(fmt, args)
#endif

/* Stack alignment */
#if COMPILER_GCC || COMPILER_CLANG
#  define FORCE_STACK_ALIGN(n) __attribute__((force_align_arg_pointer))
#else
#  define FORCE_STACK_ALIGN(n)
#endif

/* Used to mark a function as a syscall */
#define SYSCALL             HIDDEN

/* Vector table entry */
#define VECTOR_ENTRY        SECTION(".text.vector")

/* Interrupt handler */
#define ISR                 HIDDEN NOINLINE

/* Memory barriers */
#define DMB()               __sync_synchronize()
#define DSB()               __sync_synchronize()
#define ISB()               __sync_synchronize()

/* Atomic operations (GCC builtins) */
#define ATOMIC_ADD(ptr, val)     __sync_fetch_and_add((ptr), (val))
#define ATOMIC_SUB(ptr, val)     __sync_fetch_and_sub((ptr), (val))
#define ATOMIC_OR(ptr, val)      __sync_fetch_and_or((ptr), (val))
#define ATOMIC_AND(ptr, val)     __sync_fetch_and_and((ptr), (val))
#define ATOMIC_XOR(ptr, val)     __sync_fetch_and_xor((ptr), (val))
#define ATOMIC_CAS(ptr, old, new) __sync_val_compare_and_swap((ptr), (old), (new))
#define ATOMIC_SWAP(ptr, val)    __sync_lock_test_and_set((ptr), (val))

/* Endianness */
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#  define LITTLE_ENDIAN     1
#  define BIG_ENDIAN        0
#elif defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
#  define LITTLE_ENDIAN     0
#  define BIG_ENDIAN        1
#else
#  define LITTLE_ENDIAN     1
#  define BIG_ENDIAN        0
#endif

/* Byte swap */
#if COMPILER_GCC || COMPILER_CLANG
#  define BSWAP16(x)        __builtin_bswap16(x)
#  define BSWAP32(x)        __builtin_bswap32(x)
#  define BSWAP64(x)        __builtin_bswap64(x)
#else
#  define BSWAP16(x)        ((uint16_t)(((x) << 8) | (((x) >> 8) & 0xFF)))
#  define BSWAP32(x)        ((uint32_t)(BSWAP16((x) >> 16) | ((uint32_t)BSWAP16(x) << 16)))
#  define BSWAP64(x)        ((uint64_t)(BSWAP32((x) >> 32) | ((uint64_t)BSWAP32(x) << 32)))
#endif

/* Endian conversion (little-endian host) */
#if LITTLE_ENDIAN
#  define LE16(x)           (x)
#  define LE32(x)           (x)
#  define LE64(x)           (x)
#  define BE16(x)           BSWAP16(x)
#  define BE32(x)           BSWAP32(x)
#  define BE64(x)           BSWAP64(x)
#else
#  define LE16(x)           BSWAP16(x)
#  define LE32(x)           BSWAP32(x)
#  define LE64(x)           BSWAP64(x)
#  define BE16(x)           (x)
#  define BE32(x)           (x)
#  define BE64(x)           (x)
#endif

/* Read from / write to LE/BE register */
#define READ_LE16(addr)     LE16(MMIO_READ16(addr))
#define READ_LE32(addr)     LE32(MMIO_READ32(addr))
#define READ_LE64(addr)     LE64(MMIO_READ64(addr))
#define READ_BE16(addr)     BE16(MMIO_READ16(addr))
#define READ_BE32(addr)     BE32(MMIO_READ32(addr))
#define READ_BE64(addr)     BE64(MMIO_READ64(addr))
#define WRITE_LE16(addr, v) MMIO_WRITE16(addr, LE16(v))
#define WRITE_LE32(addr, v) MMIO_WRITE32(addr, LE32(v))
#define WRITE_LE64(addr, v) MMIO_WRITE64(addr, LE64(v))
#define WRITE_BE16(addr, v) MMIO_WRITE16(addr, BE16(v))
#define WRITE_BE32(addr, v) MMIO_WRITE32(addr, BE32(v))
#define WRITE_BE64(addr, v) MMIO_WRITE64(addr, BE64(v))

/* Get the return address of the current function */
#if COMPILER_GCC || COMPILER_CLANG
#  define RETURN_ADDR(n)    __builtin_return_address(n)
#  define FRAME_ADDR(n)     __builtin_frame_address(n)
#else
#  define RETURN_ADDR(n)    ((void*)0)
#  define FRAME_ADDR(n)     ((void*)0)
#endif

/* Stack pointer */
#if ARCH_X86_64
#  define READ_SP()         ({ uint64_t _sp; ASM("mov %%rsp, %0" : "=r"(_sp)); _sp; })
#  define READ_FP()         ({ uint64_t _fp; ASM("mov %%rbp, %0" : "=r"(_fp)); _fp; })
#elif ARCH_ARM64
#  define READ_SP()         ({ uint64_t _sp; ASM("mov %0, sp" : "=r"(_sp)); _sp; })
#  define READ_FP()         ({ uint64_t _fp; ASM("mov %0, x29" : "=r"(_fp)); _fp; })
#endif

#endif /* AINOS_COMPILER_H */