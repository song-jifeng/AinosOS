/*
 * AinosOS - tests/test_string.c
 * Unit tests for string library
 */

#include <types.h>
#include <lib/string.h>
#include <boot/boot.h>

static int test_count = 0;
static int pass_count = 0;

#define TEST_ASSERT(cond, msg) do { \
    test_count++; \
    if (!(cond)) { \
        boot_printf("  FAIL: %s (line %d)\n", msg, __LINE__); \
    } else { \
        pass_count++; \
    } \
} while(0)

#define TEST_RUN(name) boot_printf("Test: %s\n", name)

/*
 * Run all string tests
 */
void test_string(void) {
    boot_printf("\n=== String Library Tests ===\n");

    TEST_RUN("memset");
    {
        char buf[16];
        memset(buf, 0xAB, 16);
        for (int i = 0; i < 16; i++) {
            TEST_ASSERT(buf[i] == (char)0xAB, "memset sets correct bytes");
        }
    }

    TEST_RUN("memcpy");
    {
        char src[] = "Hello, World!";
        char dst[32] = {0};
        memcpy(dst, src, 14);
        TEST_ASSERT(memcmp(dst, src, 14) == 0, "memcpy copies correctly");
        TEST_ASSERT(dst[13] == '!', "memcpy copies last byte");
    }

    TEST_RUN("memmove - forward");
    {
        char buf[] = "Hello, World!";
        memmove(buf + 2, buf, 8);
        TEST_ASSERT(memcmp(buf, "HeHello, ", 9) == 0, "memmove forward");
    }

    TEST_RUN("memmove - backward");
    {
        char buf[] = "Hello, World!";
        memmove(buf, buf + 2, 8);
        TEST_ASSERT(memcmp(buf, "llo, Wor", 8) == 0, "memmove backward");
    }

    TEST_RUN("memcmp");
    {
        TEST_ASSERT(memcmp("abc", "abc", 3) == 0, "memcmp equal");
        TEST_ASSERT(memcmp("abc", "abd", 3) < 0, "memcmp less");
        TEST_ASSERT(memcmp("abd", "abc", 3) > 0, "memcmp greater");
    }

    TEST_RUN("memchr");
    {
        const char *s = "Hello, World!";
        TEST_ASSERT(memchr(s, 'W', 13) == s + 7, "memchr finds character");
        TEST_ASSERT(memchr(s, 'z', 13) == NULL, "memchr returns NULL when not found");
    }

    TEST_RUN("strlen");
    {
        TEST_ASSERT(strlen("") == 0, "strlen empty string");
        TEST_ASSERT(strlen("Hello") == 5, "strlen 'Hello'");
        TEST_ASSERT(strlen("Hello, World!") == 13, "strlen 'Hello, World!'");
    }

    TEST_RUN("strnlen");
    {
        TEST_ASSERT(strnlen("Hello", 3) == 3, "strnlen limited");
        TEST_ASSERT(strnlen("Hello", 10) == 5, "strnlen unlimited");
    }

    TEST_RUN("strcpy");
    {
        char dst[32];
        TEST_ASSERT(strcpy(dst, "Hello") == dst, "strcpy returns dest");
        TEST_ASSERT(strcmp(dst, "Hello") == 0, "strcpy copies correctly");
    }

    TEST_RUN("strncpy");
    {
        char dst[32];
        memset(dst, 'X', 32);
        strncpy(dst, "Hello", 3);
        TEST_ASSERT(dst[0] == 'H' && dst[1] == 'e' && dst[2] == 'l', "strncpy first 3 chars");
    }

    TEST_RUN("strcmp");
    {
        TEST_ASSERT(strcmp("abc", "abc") == 0, "strcmp equal");
        TEST_ASSERT(strcmp("abc", "abd") < 0, "strcmp less");
        TEST_ASSERT(strcmp("abd", "abc") > 0, "strcmp greater");
        TEST_ASSERT(strcmp("abc", "abcd") < 0, "strcmp with different lengths");
    }

    TEST_RUN("strncmp");
    {
        TEST_ASSERT(strncmp("abc", "abd", 2) == 0, "strncmp limited to 2");
        TEST_ASSERT(strncmp("abc", "abd", 3) < 0, "strncmp full compare");
    }

    TEST_RUN("strchr");
    {
        TEST_ASSERT(strchr("Hello", 'l') != NULL, "strchr finds 'l'");
        TEST_ASSERT(strchr("Hello", 'l') - "Hello" == 2, "strchr returns first 'l'");
        TEST_ASSERT(strchr("Hello", 'z') == NULL, "strchr returns NULL");
    }

    TEST_RUN("strrchr");
    {
        TEST_ASSERT(strrchr("Hello", 'l') - "Hello" == 3, "strrchr returns last 'l'");
    }

    TEST_RUN("strstr");
    {
        const char *s = "Hello, World!";
        TEST_ASSERT(strstr(s, "World") == s + 7, "strstr finds substring");
        TEST_ASSERT(strstr(s, "w") == NULL, "strstr case sensitive");
    }

    TEST_RUN("strspn/strcspn");
    {
        TEST_ASSERT(strspn("abc123", "abc") == 3, "strspn match");
        TEST_ASSERT(strcspn("abc123", "123") == 3, "strcspn match");
    }

    TEST_RUN("strtok");
    {
        char str[] = "one,two,three";
        char *t1 = strtok(str, ",");
        char *t2 = strtok(NULL, ",");
        char *t3 = strtok(NULL, ",");
        char *t4 = strtok(NULL, ",");
        TEST_ASSERT(t1 && strcmp(t1, "one") == 0, "strtok first token");
        TEST_ASSERT(t2 && strcmp(t2, "two") == 0, "strtok second token");
        TEST_ASSERT(t3 && strcmp(t3, "three") == 0, "strtok third token");
        TEST_ASSERT(t4 == NULL, "strtok no more tokens");
    }

    TEST_RUN("atoi/strtol");
    {
        TEST_ASSERT(atoi("123") == 123, "atoi positive");
        TEST_ASSERT(atoi("-456") == -456, "atoi negative");
        TEST_ASSERT(strtol("0xFF", NULL, 16) == 255, "strtol hex");
        TEST_ASSERT(strtol("077", NULL, 8) == 63, "strtol octal");
        TEST_ASSERT(strtol("1010", NULL, 2) == 10, "strtol binary");
    }

    TEST_RUN("isalpha/isdigit");
    {
        TEST_ASSERT(isalpha('A'), "isalpha 'A'");
        TEST_ASSERT(isalpha('z'), "isalpha 'z'");
        TEST_ASSERT(!isalpha('5'), "isalpha not digit");
        TEST_ASSERT(isdigit('5'), "isdigit '5'");
        TEST_ASSERT(!isdigit('A'), "isdigit not letter");
    }

    TEST_RUN("toupper/tolower");
    {
        TEST_ASSERT(toupper('a') == 'A', "toupper");
        TEST_ASSERT(tolower('Z') == 'z', "tolower");
    }

    boot_printf("String tests: %d/%d passed\n", pass_count, test_count);
}

/*
 * Export test runner
 */
void run_string_tests(void) {
    test_count = 0;
    pass_count = 0;
    test_string();
}