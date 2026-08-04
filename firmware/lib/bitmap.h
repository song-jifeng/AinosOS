/*
 * AinosOS - lib/bitmap.h
 * Bitmap data structure declarations
 */

#ifndef AINOS_LIB_BITMAP_H
#define AINOS_LIB_BITMAP_H

#include <types.h>

/* Bitmap operations */
void bitmap_set(uint64_t *bitmap, size_t bit);
void bitmap_clear(uint64_t *bitmap, size_t bit);
int  bitmap_test(const uint64_t *bitmap, size_t bit);
void bitmap_set_range(uint64_t *bitmap, size_t start, size_t count);
void bitmap_clear_range(uint64_t *bitmap, size_t start, size_t count);
int  bitmap_find_first_free(const uint64_t *bitmap, size_t total_bits, size_t hint);
int  bitmap_find_first_set(const uint64_t *bitmap, size_t total_bits, size_t hint);
size_t bitmap_find_free_range(const uint64_t *bitmap, size_t total_bits, size_t count, size_t align);
size_t bitmap_count_free(const uint64_t *bitmap, size_t total_bits);
size_t bitmap_count_set(const uint64_t *bitmap, size_t total_bits);
void bitmap_zero(uint64_t *bitmap, size_t bits);
void bitmap_fill(uint64_t *bitmap, size_t bits);
int  bitmap_is_full(const uint64_t *bitmap, size_t total_bits);
int  bitmap_is_empty(const uint64_t *bitmap, size_t total_bits);

/* Bitmap size helpers */
#define BITS_TO_WORDS(bits)     (((bits) + 63) / 64)
#define BITS_TO_BYTES(bits)     (BITS_TO_WORDS(bits) * 8)
#define BITMAP_DECLARE(name, bits) uint64_t name[BITS_TO_WORDS(bits)]

#endif /* AINOS_LIB_BITMAP_H */