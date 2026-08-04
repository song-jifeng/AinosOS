/*
 * AinosOS - types.h
 * Core type definitions for the firmware
 */

#ifndef AINOS_TYPES_H
#define AINOS_TYPES_H

/* Signed integer types */
typedef signed char         int8_t;
typedef short               int16_t;
typedef int                 int32_t;
typedef long long           int64_t;

/* Unsigned integer types */
typedef unsigned char       uint8_t;
typedef unsigned short      uint16_t;
typedef unsigned int        uint32_t;
typedef unsigned long long  uint64_t;

/* Pointer-width types */
typedef int32_t             intptr_t;
typedef uint32_t            uintptr_t;
typedef uint64_t            size_t;
typedef int64_t             ssize_t;

/* Address types */
typedef uint64_t            phys_addr_t;
typedef uint64_t            virt_addr_t;

/* Boolean */
typedef uint8_t             bool;
#define true                1
#define false               0

/* NULL pointer */
#define NULL                ((void*)0)

/* Register width type for x86_64 */
typedef uint64_t            reg_t;

/* Status / error return */
typedef int32_t             status_t;

/* Offsets */
typedef int64_t             off_t;

/* Fixed-width minimum-width types */
typedef signed char         int_least8_t;
typedef short               int_least16_t;
typedef int                 int_least32_t;
typedef long long           int_least64_t;
typedef unsigned char       uint_least8_t;
typedef unsigned short      uint_least16_t;
typedef unsigned int        uint_least32_t;
typedef unsigned long long  uint_least64_t;

/* Fast minimum-width types */
typedef int                 int_fast8_t;
typedef int                 int_fast16_t;
typedef int                 int_fast32_t;
typedef long long           int_fast64_t;
typedef unsigned int        uint_fast8_t;
typedef unsigned int        uint_fast16_t;
typedef unsigned int        uint_fast32_t;
typedef unsigned long long  uint_fast64_t;

/* Maximum-size integer types */
typedef long long           intmax_t;
typedef unsigned long long  uintmax_t;

/* Limits */
#define INT8_MIN            (-128)
#define INT16_MIN           (-32768)
#define INT32_MIN           (-2147483647 - 1)
#define INT64_MIN           (-9223372036854775807LL - 1)
#define INT8_MAX            127
#define INT16_MAX           32767
#define INT32_MAX           2147483647
#define INT64_MAX           9223372036854775807LL
#define UINT8_MAX           255
#define UINT16_MAX          65535
#define UINT32_MAX          4294967295U
#define UINT64_MAX          18446744073709551615ULL

#define SIZE_MAX            UINT64_MAX

/* Bit-width types for MMIO/device registers */
typedef volatile uint8_t    vreg8_t;
typedef volatile uint16_t   vreg16_t;
typedef volatile uint32_t   vreg32_t;
typedef volatile uint64_t   vreg64_t;

#endif /* AINOS_TYPES_H */