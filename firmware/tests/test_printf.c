/*
 * AinosOS - tests/test_printf.c
 * Unit tests for printf library
 */

#include <types.h>
#include <lib/printf.h>
#include <lib/string.h>
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
 * Run all printf tests
 */
void test_printf(void) {
    char buf[256];

    boot_printf("\n=== Printf Library Tests ===\n");

    TEST_RUN("sprintf simple string");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "Hello");
        TEST_ASSERT(strcmp(buf, "Hello") == 0, "sprintf simple string");
    }

    TEST_RUN("sprintf %%d");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%d", 42);
        TEST_ASSERT(strcmp(buf, "42") == 0, "sprintf %%d positive");
    }

    TEST_RUN("sprintf %%d negative");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%d", -42);
        TEST_ASSERT(strcmp(buf, "-42") == 0, "sprintf %%d negative");
    }

    TEST_RUN("sprintf %%u");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%u", 42);
        TEST_ASSERT(strcmp(buf, "42") == 0, "sprintf %%u");
    }

    TEST_RUN("sprintf %%x");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%x", 255);
        TEST_ASSERT(strcmp(buf, "ff") == 0, "sprintf %%x");
    }

    TEST_RUN("sprintf %%X");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%X", 255);
        TEST_ASSERT(strcmp(buf, "FF") == 0, "sprintf %%X");
    }

    TEST_RUN("sprintf %%s");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%s", "test");
        TEST_ASSERT(strcmp(buf, "test") == 0, "sprintf %%s");
    }

    TEST_RUN("sprintf %%c");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%c", 'A');
        TEST_ASSERT(strcmp(buf, "A") == 0, "sprintf %%c");
    }

    TEST_RUN("sprintf %%p");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%p", (void*)0x1234);
        TEST_ASSERT(strstr(buf, "0x1234") != NULL, "sprintf %%p contains 0x1234");
    }

    TEST_RUN("sprintf width");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%5d", 42);
        TEST_ASSERT(strcmp(buf, "   42") == 0, "sprintf width padding");
    }

    TEST_RUN("sprintf zero-pad");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%05d", 42);
        TEST_ASSERT(strcmp(buf, "00042") == 0, "sprintf zero-padding");
    }

    TEST_RUN("sprintf left-justify");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%-5d", 42);
        TEST_ASSERT(strcmp(buf, "42   ") == 0, "sprintf left-justify");
    }

    TEST_RUN("sprintf %%ld");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%ld", 123456L);
        TEST_ASSERT(strcmp(buf, "123456") == 0, "sprintf %%ld");
    }

    TEST_RUN("sprintf %%lld");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%lld", 123456789LL);
        TEST_ASSERT(strcmp(buf, "123456789") == 0, "sprintf %%lld");
    }

    TEST_RUN("sprintf %%llx");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%llx", 0xABCDEF123456ULL);
        TEST_ASSERT(strcmp(buf, "abcdef123456") == 0, "sprintf %%llx");
    }

    TEST_RUN("sprintf %%o");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%o", 63);
        TEST_ASSERT(strcmp(buf, "77") == 0, "sprintf %%o");
    }

    TEST_RUN("sprintf %%#x");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%#x", 255);
        TEST_ASSERT(strcmp(buf, "0xff") == 0, "sprintf %%#x");
    }

    TEST_RUN("sprintf %%#X");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%#X", 255);
        TEST_ASSERT(strcmp(buf, "0XFF") == 0, "sprintf %%#X");
    }

    TEST_RUN("sprintf %%+d");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%+d", 42);
        TEST_ASSERT(strcmp(buf, "+42") == 0, "sprintf %%+d");
    }

    TEST_RUN("sprintf multiple args");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%s %d %x", "test", 42, 0xFF);
        TEST_ASSERT(strcmp(buf, "test 42 ff") == 0, "sprintf multiple args");
    }

    TEST_RUN("sprintf precision");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%.5d", 42);
        TEST_ASSERT(strcmp(buf, "00042") == 0, "sprintf precision");
    }

    TEST_RUN("sprintf %%");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "100%%");
        TEST_ASSERT(strcmp(buf, "100%") == 0, "sprintf %%");
    }

    TEST_RUN("sprintf zero value");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%d", 0);
        TEST_ASSERT(strcmp(buf, "0") == 0, "sprintf zero value");
    }

    TEST_RUN("sprintf null string");
    {
        memset(buf, 0, sizeof(buf));
        sprintf(buf, "%s", (char*)NULL);
        TEST_ASSERT(strcmp(buf, "(null)") == 0, "sprintf null string");
    }

    TEST_RUN("snprintf truncation");
    {
        memset(buf, 0, sizeof(buf));
        int result = snprintf(buf, 5, "Hello, World!");
        TEST_ASSERT(strcmp(buf, "Hell") == 0, "snprintf truncates");
        TEST_ASSERT(result == 13, "snprintf returns full length");
    }

    boot_printf("Printf tests: %d/%d passed\n", pass_count, test_count);
}

void run_printf_tests(void) {
    test_count = 0;
    pass_count = 0;
    test_printf();
}