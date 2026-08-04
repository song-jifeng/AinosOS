/*
 * AinosOS - macros.h
 * Utility macros used throughout the firmware
 */

#ifndef AINOS_MACROS_H
#define AINOS_MACROS_H

/* Alignment macros */
#define ALIGN_UP(x, align)          (((x) + ((align) - 1)) & ~((align) - 1))
#define ALIGN_DOWN(x, align)        ((x) & ~((align) - 1))
#define IS_ALIGNED(x, align)        (((x) & ((align) - 1)) == 0)

/* Bit manipulation */
#define BIT(n)                      (1ULL << (n))
#define BIT_MASK(n)                 (BIT(n) - 1)
#define BIT_SET(x, n)               ((x) |= BIT(n))
#define BIT_CLEAR(x, n)             ((x) &= ~BIT(n))
#define BIT_TEST(x, n)              (((x) & BIT(n)) != 0)
#define BIT_RANGE(h, l)             ((BIT_MASK((h) - (l) + 1) << (l)))

/* Field extraction and insertion */
#define FIELD_GET(val, mask, shift) (((val) >> (shift)) & (mask))
#define FIELD_SET(val, mask, shift, v) \
    (((val) & ~((mask) << (shift))) | (((v) & (mask)) << (shift)))

/* Array helpers */
#define ARRAY_SIZE(arr)             (sizeof(arr) / sizeof((arr)[0]))
#define ARRAY_END(arr)              ((arr) + ARRAY_SIZE(arr))
#define MIN(a, b)                   ((a) < (b) ? (a) : (b))
#define MAX(a, b)                   ((a) > (b) ? (a) : (b))
#define CLAMP(x, lo, hi)            ((x) < (lo) ? (lo) : (x) > (hi) ? (hi) : (x))

/* Absolute value */
#define ABS(x)                      ((x) < 0 ? -(x) : (x))

/* Offset of a member in a struct */
#define OFFSET_OF(type, member)     ((size_t)&((type*)0)->member)

/* Container of a member */
#define CONTAINER_OF(ptr, type, member) \
    ((type*)((char*)(ptr) - OFFSET_OF(type, member)))

/* Division with rounding up */
#define DIV_ROUND_UP(n, d)          (((n) + (d) - 1) / (d))
#define DIV_ROUND_CLOSEST(n, d)     (((n) + (d) / 2) / (d))

/* Page size definitions */
#define PAGE_SIZE                   4096
#define PAGE_SHIFT                  12
#define PAGE_MASK                   (PAGE_SIZE - 1)
#define PAGE_ALIGN_UP(x)            ALIGN_UP(x, PAGE_SIZE)
#define PAGE_ALIGN_DOWN(x)          ALIGN_DOWN(x, PAGE_SIZE)
#define PAGE_COUNT(x)               DIV_ROUND_UP(x, PAGE_SIZE)

/* 2 MiB huge page */
#define HUGE_PAGE_SIZE              (2 * 1024 * 1024)
#define HUGE_PAGE_SHIFT             21
#define HUGE_PAGE_MASK              (HUGE_PAGE_SIZE - 1)

/* 1 GiB huge page */
#define GIBI_PAGE_SIZE              (1024 * 1024 * 1024ULL)
#define GIBI_PAGE_SHIFT             30

/* KiB, MiB, GiB */
#define KIB(x)                      ((x) * 1024ULL)
#define MIB(x)                      ((x) * 1024ULL * 1024ULL)
#define GIB(x)                      ((x) * 1024ULL * 1024ULL * 1024ULL)

/* Packed attribute */
#define PACKED                      __attribute__((packed))
#define ALIGNED(n)                  __attribute__((aligned(n)))
#define SECTION(s)                  __attribute__((section(s)))
#define USED                        __attribute__((used))
#define UNUSED                      __attribute__((unused))
#define WEAK                        __attribute__((weak))
#define INLINE                      static inline __attribute__((always_inline))
#define NOINLINE                    __attribute__((noinline))
#define NORETURN                    __attribute__((noreturn))
#define PRINTF_FORMAT(fmt, args)    __attribute__((format(printf, fmt, args)))

/* Barrier macros */
#define MEMORY_BARRIER()            __sync_synchronize()
#define COMPILER_BARRIER()          __asm__ volatile("" ::: "memory")

/* Spinloop hint */
#define SPINLOCK_HINT()             __asm__ volatile("pause")

/* Likely / Unlikely */
#define likely(x)                   __builtin_expect(!!(x), 1)
#define unlikely(x)                 __builtin_expect(!!(x), 0)

/* Stringify */
#define STRINGIFY(x)                #x
#define TOSTRING(x)                 STRINGIFY(x)

/* Static assertion */
#define STATIC_ASSERT(cond, msg)    typedef char static_assert_##msg[(cond) ? 1 : -1] __attribute__((unused))

/* Suppress unused variable warning */
#define UNUSED_VAR(x)               ((void)(x))

/* Defer / Scope cleanup */
#define DEFER_IMPL(line, ...)       auto void _defer_cleanup_##line(void *); \
                                    __attribute__((cleanup(_defer_cleanup_##line))) \
                                    void *_defer_var_##line = NULL; \
                                    void _defer_cleanup_##line(__attribute__((unused)) void *v) { __VA_ARGS__; }
#define DEFER(...)                  DEFER_IMPL(__LINE__, __VA_ARGS__)

/* Return min/max for 3 values */
#define MIN3(a, b, c)               MIN(MIN(a, b), c)
#define MAX3(a, b, c)               MAX(MAX(a, b), c)

/* Swap two values */
#define SWAP(a, b)                  do { typeof(a) _tmp = (a); (a) = (b); (b) = _tmp; } while (0)

/* Count leading zeros (GCC builtin) */
#define CLZ(x)                      __builtin_clzll(x)
#define CTZ(x)                      __builtin_ctzll(x)
#define POPCOUNT(x)                 __builtin_popcountll(x)

/* Find first set bit (1-indexed, 0 if none) */
#define FFS(x)                      __builtin_ffsll(x)

/* Memory-mapped IO access */
#define MMIO_READ8(addr)            (*(volatile uint8_t*)(addr))
#define MMIO_READ16(addr)           (*(volatile uint16_t*)(addr))
#define MMIO_READ32(addr)           (*(volatile uint32_t*)(addr))
#define MMIO_READ64(addr)           (*(volatile uint64_t*)(addr))
#define MMIO_WRITE8(addr, val)      (*(volatile uint8_t*)(addr) = (val))
#define MMIO_WRITE16(addr, val)     (*(volatile uint16_t*)(addr) = (val))
#define MMIO_WRITE32(addr, val)     (*(volatile uint32_t*)(addr) = (val))
#define MMIO_WRITE64(addr, val)     (*(volatile uint64_t*)(addr) = (val))

/* Physical address <-> virtual address conversions (set by boot code) */
extern uint64_t _kernel_phys_offset;
#define PHYS_TO_VIRT(pa)            ((void*)((uint64_t)(pa) + _kernel_phys_offset))
#define VIRT_TO_PHYS(va)            ((uint64_t)(va) - _kernel_phys_offset)

#endif /* AINOS_MACROS_H */