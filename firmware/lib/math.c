/*
 * AinosOS - lib/math.c
 * Math utility functions
 */

#include <types.h>
#include <lib/math.h>

/* Simple LCG PRNG state */
static uint64_t prng_state = 0x1234567890ABCDEFULL;

/*
 * Absolute value
 */
int64_t abs(int64_t x) {
    return x < 0 ? -x : x;
}

/*
 * Minimum of two values
 */
int64_t min(int64_t a, int64_t b) {
    return a < b ? a : b;
}

/*
 * Maximum of two values
 */
int64_t max(int64_t a, int64_t b) {
    return a > b ? a : b;
}

/*
 * Clamp a value to a range
 */
int64_t clamp(int64_t val, int64_t lo, int64_t hi) {
    if (val < lo) return lo;
    if (val > hi) return hi;
    return val;
}

/*
 * Division with rounding up
 */
uint64_t div_round_up(uint64_t n, uint64_t d) {
    if (d == 0) return 0;
    return (n + d - 1) / d;
}

/*
 * Division with rounding to closest
 */
uint64_t div_round_closest(uint64_t n, uint64_t d) {
    if (d == 0) return 0;
    return (n + d / 2) / d;
}

/*
 * Greatest common divisor
 */
int64_t gcd(int64_t a, int64_t b) {
    a = abs(a);
    b = abs(b);
    while (b != 0) {
        int64_t t = b;
        b = a % b;
        a = t;
    }
    return a;
}

/*
 * Least common multiple
 */
int64_t lcm(int64_t a, int64_t b) {
    if (a == 0 || b == 0) return 0;
    return abs(a) / gcd(a, b) * abs(b);
}

/*
 * Power of 2
 */
uint64_t pow2(uint64_t exp) {
    if (exp >= 64) return 0;
    return 1ULL << exp;
}

/*
 * Base-2 logarithm (floor)
 */
uint64_t log2(uint64_t x) {
    if (x == 0) return 0;
    return 63 - __builtin_clzll(x);
}

/*
 * Base-2 logarithm (ceiling)
 */
uint64_t log2_round_up(uint64_t x) {
    if (x <= 1) return 0;
    uint64_t l = log2(x);
    if (pow2(l) < x) l++;
    return l;
}

/*
 * Check if x is a power of 2
 */
uint64_t is_power_of_2(uint64_t x) {
    return x && !(x & (x - 1));
}

/*
 * Round up to the next power of 2
 */
uint64_t round_up_pow2(uint64_t x) {
    if (x == 0) return 1;
    if (is_power_of_2(x)) return x;
    return 1ULL << (log2(x) + 1);
}

/*
 * Round down to the previous power of 2
 */
uint64_t round_down_pow2(uint64_t x) {
    if (x == 0) return 0;
    return 1ULL << log2(x);
}

/*
 * Population count (64-bit)
 */
int popcount64(uint64_t x) {
    return __builtin_popcountll(x);
}

/*
 * Population count (32-bit)
 */
int popcount32(uint32_t x) {
    return __builtin_popcount(x);
}

/*
 * Count trailing zeros (64-bit)
 */
int ctz64(uint64_t x) {
    if (x == 0) return 64;
    return __builtin_ctzll(x);
}

/*
 * Count leading zeros (64-bit)
 */
int clz64(uint64_t x) {
    if (x == 0) return 64;
    return __builtin_clzll(x);
}

/*
 * Find last set bit (1-indexed, 0 if none)
 */
int fls64(uint64_t x) {
    if (x == 0) return 0;
    return 64 - __builtin_clzll(x);
}

/*
 * Find first set bit (1-indexed, 0 if none)
 */
int ffs64(uint64_t x) {
    if (x == 0) return 0;
    return __builtin_ctzll(x) + 1;
}

/*
 * Convert integer to soft float
 */
soft_float int_to_soft_float(int64_t i) {
    soft_float f;
    f.sign = i < 0 ? 1 : 0;
    f.mantissa = (uint64_t)(i < 0 ? -i : i);
    f.exponent = 0;
    while (f.mantissa > 0 && !(f.mantissa & 0x8000000000000000ULL)) {
        f.mantissa <<= 1;
        f.exponent--;
    }
    return f;
}

/*
 * Convert soft float to integer
 */
int64_t soft_float_to_int(soft_float f) {
    uint64_t mant = f.mantissa;
    int16_t exp = f.exponent;
    while (exp < 0) {
        mant >>= 1;
        exp++;
    }
    while (exp > 0 && mant <= 0x7FFFFFFFFFFFFFFFULL) {
        mant <<= 1;
        exp--;
    }
    return f.sign ? -(int64_t)mant : (int64_t)mant;
}

/*
 * Soft float add
 */
soft_float soft_float_add(soft_float a, soft_float b) {
    /* Align exponents */
    while (a.exponent < b.exponent) { a.mantissa >>= 1; a.exponent++; }
    while (b.exponent < a.exponent) { b.mantissa >>= 1; b.exponent++; }

    soft_float result;
    if (a.sign == b.sign) {
        result.mantissa = a.mantissa + b.mantissa;
        result.sign = a.sign;
    } else if (a.mantissa >= b.mantissa) {
        result.mantissa = a.mantissa - b.mantissa;
        result.sign = a.sign;
    } else {
        result.mantissa = b.mantissa - a.mantissa;
        result.sign = b.sign;
    }
    result.exponent = a.exponent;

    /* Normalize */
    while (result.mantissa > 0 && !(result.mantissa & 0x8000000000000000ULL)) {
        result.mantissa <<= 1;
        result.exponent--;
    }

    return result;
}

/*
 * Soft float subtract
 */
soft_float soft_float_sub(soft_float a, soft_float b) {
    b.sign = !b.sign;
    return soft_float_add(a, b);
}

/*
 * Soft float multiply
 */
soft_float soft_float_mul(soft_float a, soft_float b) {
    soft_float result;
    result.sign = a.sign ^ b.sign;
    /* Use upper 64 bits of 128-bit product */
    __uint128_t product = (__uint128_t)a.mantissa * b.mantissa;
    result.mantissa = (uint64_t)(product >> 64);
    result.exponent = a.exponent + b.exponent + 64;

    /* Normalize */
    while (result.mantissa > 0 && !(result.mantissa & 0x8000000000000000ULL)) {
        result.mantissa <<= 1;
        result.exponent--;
    }

    return result;
}

/*
 * Soft float divide
 */
soft_float soft_float_div(soft_float a, soft_float b) {
    if (b.mantissa == 0) {
        soft_float nan = { 0, 0, 0 };
        return nan;
    }

    soft_float result;
    result.sign = a.sign ^ b.sign;
    result.mantissa = (uint64_t)(((__uint128_t)a.mantissa << 64) / b.mantissa);
    result.exponent = a.exponent - b.exponent - 64;

    /* Normalize */
    while (result.mantissa > 0 && !(result.mantissa & 0x8000000000000000ULL)) {
        result.mantissa <<= 1;
        result.exponent--;
    }

    return result;
}

/*
 * Simple LCG random number generator
 */
uint32_t rand32(void) {
    prng_state = prng_state * 6364136223846793005ULL + 1442695040888963407ULL;
    return (uint32_t)(prng_state >> 32);
}

/*
 * Generate 64-bit random number
 */
uint64_t rand64(void) {
    return ((uint64_t)rand32() << 32) | rand32();
}

/*
 * Seed the random number generator
 */
void srand(uint64_t seed) {
    prng_state = seed;
    rand32();  /* Warm up */
    rand32();
}

/*
 * Generate random number in range [min, max]
 */
uint32_t rand_range(uint32_t min, uint32_t max) {
    if (min > max) return min;
    uint32_t range = max - min + 1;
    return min + (rand32() % range);
}