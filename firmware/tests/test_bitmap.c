/*
 * AinosOS - tests/test_bitmap.c
 * Unit tests for bitmap library
 */

#include <types.h>
#include <lib/bitmap.h>
#include <boot/boot.h>

static int test_count = 0;
static int pass_count = 0;

#define TEST_ASSERT(cond, msg) do { \
    test_count++; \
    if (!(cond)) { \
        boot_printf("  FAIL: %s\n", msg); \
    } else { \
        pass_count++; \
    } \
} while(0)

/*
 * Run all bitmap tests
 */
void test_bitmap(void) {
    boot_printf("\n=== Bitmap Library Tests ===\n");

    BITMAP_DECLARE(bm, 256);

    TEST_RUN("bitmap_zero");
    bitmap_zero(bm, 256);
    TEST_ASSERT(bitmap_is_empty(bm, 256), "bitmap_zero clears all bits");

    TEST_RUN("bitmap_set/test");
    bitmap_set(bm, 10);
    TEST_ASSERT(bitmap_test(bm, 10), "bitmap_test returns true for set bit");
    TEST_ASSERT(!bitmap_test(bm, 11), "bitmap_test returns false for clear bit");

    TEST_RUN("bitmap_clear");
    bitmap_clear(bm, 10);
    TEST_ASSERT(!bitmap_test(bm, 10), "bitmap_clear clears bit");

    TEST_RUN("bitmap_set_range");
    bitmap_zero(bm, 256);
    bitmap_set_range(bm, 5, 10);
    for (int i = 5; i < 15; i++) {
        TEST_ASSERT(bitmap_test(bm, i), "bitmap_set_range sets range");
    }
    TEST_ASSERT(!bitmap_test(bm, 4), "bitmap_set_range doesn't affect before");
    TEST_ASSERT(!bitmap_test(bm, 15), "bitmap_set_range doesn't affect after");

    TEST_RUN("bitmap_clear_range");
    bitmap_clear_range(bm, 7, 5);
    for (int i = 7; i < 12; i++) {
        TEST_ASSERT(!bitmap_test(bm, i), "bitmap_clear_range clears range");
    }

    TEST_RUN("bitmap_find_first_free");
    bitmap_zero(bm, 256);
    int free_bit = bitmap_find_first_free(bm, 256, 0);
    TEST_ASSERT(free_bit == 0, "bitmap_find_first_free returns 0 on empty bitmap");

    bitmap_set(bm, 0);
    bitmap_set(bm, 1);
    bitmap_set(bm, 2);
    free_bit = bitmap_find_first_free(bm, 256, 0);
    TEST_ASSERT(free_bit == 3, "bitmap_find_first_free returns 3");

    TEST_RUN("bitmap_find_first_set");
    bitmap_zero(bm, 256);
    bitmap_set(bm, 42);
    int set_bit = bitmap_find_first_set(bm, 256, 0);
    TEST_ASSERT(set_bit == 42, "bitmap_find_first_set returns 42");

    TEST_RUN("bitmap_find_free_range");
    bitmap_zero(bm, 256);
    bitmap_set_range(bm, 0, 10);
    bitmap_set_range(bm, 20, 10);
    size_t range = bitmap_find_free_range(bm, 256, 5, 1);
    TEST_ASSERT(range == 10, "bitmap_find_free_range returns 10");

    TEST_RUN("bitmap_count_free");
    bitmap_zero(bm, 256);
    TEST_ASSERT(bitmap_count_free(bm, 256) == 256, "bitmap_count_free all free");
    bitmap_set_range(bm, 0, 100);
    TEST_ASSERT(bitmap_count_free(bm, 256) == 156, "bitmap_count_free 156 free");

    TEST_RUN("bitmap_fill");
    bitmap_fill(bm, 256);
    TEST_ASSERT(bitmap_is_full(bm, 256), "bitmap_fill sets all bits");

    TEST_RUN("bitmap_is_empty");
    bitmap_zero(bm, 256);
    TEST_ASSERT(bitmap_is_empty(bm, 256), "bitmap_is_empty true");

    TEST_RUN("bitmap_is_full");
    bitmap_fill(bm, 256);
    TEST_ASSERT(bitmap_is_full(bm, 256), "bitmap_is_full true");

    boot_printf("Bitmap tests: %d/%d passed\n", pass_count, test_count);
}

void run_bitmap_tests(void) {
    test_count = 0;
    pass_count = 0;
    test_bitmap();
}