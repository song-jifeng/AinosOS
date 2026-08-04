/*
 * AinosOS - lib/math.h
 * Math function declarations
 */

#ifndef AINOS_LIB_MATH_H
#define AINOS_LIB_MATH_H

#include <types.h>

/* Integer math */
int64_t abs(int64_t x);
int64_t min(int64_t a, int64_t b);
int64_t max(int64_t a, int64_t b);
int64_t clamp(int64_t val, int64_t lo, int64_t hi);
uint64_t div_round_up(uint64_t n, uint64_t d);
uint64_t div_round_closest(uint64_t n, uint64_t d);
int64_t gcd(int64_t a, int64_t b);
int64_t lcm(int64_t a, int64_t b);

/* Power and log */
uint64_t pow2(uint64_t exp);
uint64_t log2(uint64_t x);
uint64_t log2_round_up(uint64_t x);
uint64_t is_power_of_2(uint64_t x);
uint64_t round_up_pow2(uint64_t x);
uint64_t round_down_pow2(uint64_t x);

/* Bit operations */
int popcount64(uint64_t x);
int popcount32(uint32_t x);
int ctz64(uint64_t x);  /* Count trailing zeros */
int clz64(uint64_t x);  /* Count leading zeros */
int fls64(uint64_t x);  /* Find last set (position of MSB, 1-indexed) */
int ffs64(uint64_t x);  /* Find first set (position of LSB, 1-indexed) */

/* Floating point emulation */
typedef struct {
    uint64_t mantissa;
    int16_t exponent;
    uint8_t sign;
} soft_float;

soft_float int_to_soft_float(int64_t i);
int64_t soft_float_to_int(soft_float f);
soft_float soft_float_add(soft_float a, soft_float b);
soft_float soft_float_sub(soft_float a, soft_float b);
soft_float soft_float_mul(soft_float a, soft_float b);
soft_float soft_float_div(soft_float a, soft_float b);

/* Random number generation */
uint32_t rand32(void);
uint64_t rand64(void);
void srand(uint64_t seed);
uint32_t rand_range(uint32_t min, uint32_t max);

#endif /* AINOS_LIB_MATH_H */