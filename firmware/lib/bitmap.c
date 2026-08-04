/*
 * AinosOS - lib/bitmap.c
 * Bitmap data structure implementation
 */

#include <types.h>
#include <lib/bitmap.h>

/*
 * Set a single bit in the bitmap
 */
void bitmap_set(uint64_t *bitmap, size_t bit) {
    bitmap[bit / 64] |= (1ULL << (bit % 64));
}

/*
 * Clear a single bit in the bitmap
 */
void bitmap_clear(uint64_t *bitmap, size_t bit) {
    bitmap[bit / 64] &= ~(1ULL << (bit % 64));
}

/*
 * Test if a single bit is set
 */
int bitmap_test(const uint64_t *bitmap, size_t bit) {
    return (bitmap[bit / 64] >> (bit % 64)) & 1;
}

/*
 * Set a range of bits
 */
void bitmap_set_range(uint64_t *bitmap, size_t start, size_t count) {
    for (size_t i = 0; i < count; i++) {
        bitmap_set(bitmap, start + i);
    }
}

/*
 * Clear a range of bits
 */
void bitmap_clear_range(uint64_t *bitmap, size_t start, size_t count) {
    for (size_t i = 0; i < count; i++) {
        bitmap_clear(bitmap, start + i);
    }
}

/*
 * Find the first free bit starting from hint
 * Returns -1 if no free bit found
 */
int bitmap_find_first_free(const uint64_t *bitmap, size_t total_bits, size_t hint) {
    size_t num_words = BITS_TO_WORDS(total_bits);

    /* Search from hint to end */
    for (size_t w = hint / 64; w < num_words; w++) {
        uint64_t word = bitmap[w];
        if (w == hint / 64 && (hint % 64)) {
            /* Mask out bits before hint */
            word |= ~((1ULL << (hint % 64)) - 1);
        }
        if (word != ~0ULL) {
            int bit = __builtin_ctzll(~word);
            size_t result = w * 64 + bit;
            if (result < total_bits) return result;
            return -1;
        }
    }

    /* Search from 0 to hint */
    for (size_t w = 0; w <= hint / 64 && w < num_words; w++) {
        uint64_t word = bitmap[w];
        if (word == ~0ULL) continue;
        int bit = __builtin_ctzll(~word);
        size_t result = w * 64 + bit;
        if (result < total_bits) return result;
    }

    return -1;
}

/*
 * Find the first set bit starting from hint
 */
int bitmap_find_first_set(const uint64_t *bitmap, size_t total_bits, size_t hint) {
    size_t num_words = BITS_TO_WORDS(total_bits);

    for (size_t w = hint / 64; w < num_words; w++) {
        uint64_t word = bitmap[w];
        if (w == hint / 64 && (hint % 64)) {
            word &= ~((1ULL << (hint % 64)) - 1);
        }
        if (word != 0) {
            int bit = __builtin_ctzll(word);
            size_t result = w * 64 + bit;
            if (result < total_bits) return result;
            return -1;
        }
    }

    for (size_t w = 0; w <= hint / 64 && w < num_words; w++) {
        uint64_t word = bitmap[w];
        if (word == 0) continue;
        int bit = __builtin_ctzll(word);
        size_t result = w * 64 + bit;
        if (result < total_bits) return result;
    }

    return -1;
}

/*
 * Find a contiguous free range of at least 'count' bits
 * Returns the starting bit index, or (size_t)-1 if not found
 */
size_t bitmap_find_free_range(const uint64_t *bitmap, size_t total_bits,
                               size_t count, size_t align) {
    size_t num_words = BITS_TO_WORDS(total_bits);
    size_t consecutive = 0;

    for (size_t i = 0; i < total_bits; i++) {
        if (!bitmap_test(bitmap, i)) {
            if (consecutive == 0 && align > 1 && (i % align) != 0) {
                /* Skip to next aligned position */
                i = ALIGN_UP(i, align) - 1;
                continue;
            }
            consecutive++;
            if (consecutive == count) {
                return i - count + 1;
            }
        } else {
            consecutive = 0;
        }
    }

    return (size_t)-1;
}

/*
 * Count free bits
 */
size_t bitmap_count_free(const uint64_t *bitmap, size_t total_bits) {
    size_t num_words = BITS_TO_WORDS(total_bits);
    size_t count = 0;

    for (size_t w = 0; w < num_words; w++) {
        count += __builtin_popcountll(~bitmap[w]);
    }

    /* Adjust for unused bits in the last word */
    size_t extra_bits = num_words * 64 - total_bits;
    if (extra_bits > 0) {
        count -= extra_bits;  /* Unused bits count as "set" */
    }

    return count;
}

/*
 * Count set bits
 */
size_t bitmap_count_set(const uint64_t *bitmap, size_t total_bits) {
    return total_bits - bitmap_count_free(bitmap, total_bits);
}

/*
 * Zero the entire bitmap
 */
void bitmap_zero(uint64_t *bitmap, size_t bits) {
    size_t num_words = BITS_TO_WORDS(bits);
    for (size_t i = 0; i < num_words; i++) {
        bitmap[i] = 0;
    }
}

/*
 * Set all bits in the bitmap
 */
void bitmap_fill(uint64_t *bitmap, size_t bits) {
    size_t num_words = BITS_TO_WORDS(bits);
    for (size_t i = 0; i < num_words; i++) {
        bitmap[i] = ~0ULL;
    }
    /* Clear extra bits in the last word */
    size_t extra_bits = num_words * 64 - bits;
    if (extra_bits > 0) {
        bitmap[num_words - 1] >>= extra_bits;
    }
}

/*
 * Check if the bitmap is full (all bits set)
 */
int bitmap_is_full(const uint64_t *bitmap, size_t total_bits) {
    return bitmap_count_free(bitmap, total_bits) == 0;
}

/*
 * Check if the bitmap is empty (all bits clear)
 */
int bitmap_is_empty(const uint64_t *bitmap, size_t total_bits) {
    size_t num_words = BITS_TO_WORDS(total_bits);
    for (size_t w = 0; w < num_words; w++) {
        if (bitmap[w] != 0) return 0;
    }
    return 1;
}