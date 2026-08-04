/*
 * AinosOS - lib/string.c
 * String and memory manipulation functions
 */

#include <types.h>
#include <lib/string.h>

/*
 * Fill memory with a constant byte
 */
void *memset(void *s, int c, size_t n) {
    unsigned char *p = (unsigned char*)s;
    for (size_t i = 0; i < n; i++) {
        p[i] = (unsigned char)c;
    }
    return s;
}

/*
 * Copy memory region (non-overlapping)
 */
void *memcpy(void *dest, const void *src, size_t n) {
    unsigned char *d = (unsigned char*)dest;
    const unsigned char *s = (const unsigned char*)src;
    for (size_t i = 0; i < n; i++) {
        d[i] = s[i];
    }
    return dest;
}

/*
 * Copy memory region (may overlap)
 */
void *memmove(void *dest, const void *src, size_t n) {
    unsigned char *d = (unsigned char*)dest;
    const unsigned char *s = (const unsigned char*)src;

    if (d < s) {
        for (size_t i = 0; i < n; i++) {
            d[i] = s[i];
        }
    } else if (d > s) {
        for (size_t i = n; i > 0; i--) {
            d[i - 1] = s[i - 1];
        }
    }
    return dest;
}

/*
 * Compare two memory regions
 */
int memcmp(const void *s1, const void *s2, size_t n) {
    const unsigned char *p1 = (const unsigned char*)s1;
    const unsigned char *p2 = (const unsigned char*)s2;

    for (size_t i = 0; i < n; i++) {
        if (p1[i] != p2[i]) {
            return p1[i] - p2[i];
        }
    }
    return 0;
}

/*
 * Find first occurrence of a byte in memory
 */
void *memchr(const void *s, int c, size_t n) {
    const unsigned char *p = (const unsigned char*)s;
    for (size_t i = 0; i < n; i++) {
        if (p[i] == (unsigned char)c) {
            return (void*)&p[i];
        }
    }
    return NULL;
}

/*
 * Find last occurrence of a byte in memory
 */
void *memrchr(const void *s, int c, size_t n) {
    const unsigned char *p = (const unsigned char*)s;
    for (size_t i = n; i > 0; i--) {
        if (p[i - 1] == (unsigned char)c) {
            return (void*)&p[i - 1];
        }
    }
    return NULL;
}

/*
 * Copy memory until a character is found, or n bytes copied
 */
void *memccpy(void *dest, const void *src, int c, size_t n) {
    unsigned char *d = (unsigned char*)dest;
    const unsigned char *s = (const unsigned char*)src;

    for (size_t i = 0; i < n; i++) {
        d[i] = s[i];
        if (s[i] == (unsigned char)c) {
            return &d[i + 1];
        }
    }
    return NULL;
}

/*
 * Find a sub-memory region in memory
 */
void *memmem(const void *haystack, size_t hlen, const void *needle, size_t nlen) {
    if (nlen == 0) return (void*)haystack;
    if (nlen > hlen) return NULL;

    const unsigned char *h = (const unsigned char*)haystack;
    const unsigned char *n = (const unsigned char*)needle;

    for (size_t i = 0; i <= hlen - nlen; i++) {
        if (memcmp(&h[i], n, nlen) == 0) {
            return (void*)&h[i];
        }
    }
    return NULL;
}

/*
 * Zero memory
 */
void bzero(void *s, size_t n) {
    memset(s, 0, n);
}

/*
 * Get string length
 */
size_t strlen(const char *s) {
    size_t len = 0;
    while (s[len]) len++;
    return len;
}

/*
 * Get string length with max limit
 */
size_t strnlen(const char *s, size_t maxlen) {
    size_t len = 0;
    while (len < maxlen && s[len]) len++;
    return len;
}

/*
 * Copy string
 */
char *strcpy(char *dest, const char *src) {
    char *d = dest;
    while ((*d++ = *src++)) ;
    return dest;
}

/*
 * Copy string with max length
 */
char *strncpy(char *dest, const char *src, size_t n) {
    size_t i;
    for (i = 0; i < n && src[i]; i++) {
        dest[i] = src[i];
    }
    for (; i < n; i++) {
        dest[i] = '\0';
    }
    return dest;
}

/*
 * Concatenate strings
 */
char *strcat(char *dest, const char *src) {
    char *d = dest;
    while (*d) d++;
    while ((*d++ = *src++)) ;
    return dest;
}

/*
 * Concatenate with max length
 */
char *strncat(char *dest, const char *src, size_t n) {
    char *d = dest;
    while (*d) d++;
    for (size_t i = 0; i < n && src[i]; i++) {
        d[i] = src[i];
    }
    d[n] = '\0';
    return dest;
}

/*
 * Compare strings
 */
int strcmp(const char *s1, const char *s2) {
    while (*s1 && (*s1 == *s2)) {
        s1++;
        s2++;
    }
    return *(unsigned char*)s1 - *(unsigned char*)s2;
}

/*
 * Compare strings with max length
 */
int strncmp(const char *s1, const char *s2, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (s1[i] != s2[i]) {
            return (unsigned char)s1[i] - (unsigned char)s2[i];
        }
        if (s1[i] == '\0') break;
    }
    return 0;
}

/*
 * Case-insensitive compare
 */
int strcasecmp(const char *s1, const char *s2) {
    while (*s1 && (tolower(*s1) == tolower(*s2))) {
        s1++;
        s2++;
    }
    return tolower((unsigned char)*s1) - tolower((unsigned char)*s2);
}

/*
 * Case-insensitive compare with max length
 */
int strncasecmp(const char *s1, const char *s2, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (tolower((unsigned char)s1[i]) != tolower((unsigned char)s2[i])) {
            return tolower((unsigned char)s1[i]) - tolower((unsigned char)s2[i]);
        }
        if (s1[i] == '\0') break;
    }
    return 0;
}

/*
 * Find first occurrence of a character in a string
 */
char *strchr(const char *s, int c) {
    while (*s) {
        if (*s == (char)c) return (char*)s;
        s++;
    }
    return (c == '\0') ? (char*)s : NULL;
}

/*
 * Find last occurrence of a character in a string
 */
char *strrchr(const char *s, int c) {
    const char *last = NULL;
    while (*s) {
        if (*s == (char)c) last = s;
        s++;
    }
    if (c == '\0') return (char*)s;
    return (char*)last;
}

/*
 * Find substring in string
 */
char *strstr(const char *haystack, const char *needle) {
    size_t nlen = strlen(needle);
    if (nlen == 0) return (char*)haystack;

    while (*haystack) {
        if (strncmp(haystack, needle, nlen) == 0) {
            return (char*)haystack;
        }
        haystack++;
    }
    return NULL;
}

/*
 * Find first occurrence of any character from accept in s
 */
char *strpbrk(const char *s, const char *accept) {
    while (*s) {
        const char *a = accept;
        while (*a) {
            if (*s == *a) return (char*)s;
            a++;
        }
        s++;
    }
    return NULL;
}

/*
 * Calculate length of initial segment of s consisting of characters in accept
 */
size_t strspn(const char *s, const char *accept) {
    size_t count = 0;
    while (*s) {
        const char *a = accept;
        int found = 0;
        while (*a) {
            if (*s == *a) { found = 1; break; }
            a++;
        }
        if (!found) break;
        count++;
        s++;
    }
    return count;
}

/*
 * Calculate length of initial segment of s not containing characters in reject
 */
size_t strcspn(const char *s, const char *reject) {
    size_t count = 0;
    while (*s) {
        const char *r = reject;
        while (*r) {
            if (*s == *r) return count;
            r++;
        }
        count++;
        s++;
    }
    return count;
}

/*
 * Split string into tokens (reentrant)
 */
char *strtok_r(char *str, const char *delim, char **saveptr) {
    if (str == NULL) {
        str = *saveptr;
    }

    /* Skip leading delimiters */
    str += strspn(str, delim);
    if (*str == '\0') {
        *saveptr = str;
        return NULL;
    }

    /* Find the end of the token */
    char *end = str + strcspn(str, delim);
    if (*end != '\0') {
        *end++ = '\0';
    }
    *saveptr = end;
    return str;
}

/*
 * Split string into tokens (non-reentrant, uses static buffer)
 */
char *strtok(char *str, const char *delim) {
    static char *saveptr = NULL;
    if (str != NULL) {
        saveptr = NULL;
    }
    return strtok_r(str, delim, &saveptr);
}

/*
 * Duplicate a string
 */
char *strdup(const char *s) {
    size_t len = strlen(s) + 1;
    char *new = (char*)malloc(len);
    if (new) {
        memcpy(new, s, len);
    }
    return new;
}

/*
 * Duplicate a string with max length
 */
char *strndup(const char *s, size_t n) {
    size_t len = strnlen(s, n);
    char *new = (char*)malloc(len + 1);
    if (new) {
        memcpy(new, s, len);
        new[len] = '\0';
    }
    return new;
}

/*
 * Character classification
 */
int isalpha(int c) { return ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')); }
int isdigit(int c) { return (c >= '0' && c <= '9'); }
int isalnum(int c) { return isalpha(c) || isdigit(c); }
int isspace(int c) { return (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'); }
int isupper(int c) { return (c >= 'A' && c <= 'Z'); }
int islower(int c) { return (c >= 'a' && c <= 'z'); }
int isxdigit(int c) { return isdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }
int iscntrl(int c) { return (c < 32 || c == 127); }
int isgraph(int c) { return (c >= 33 && c <= 126); }
int isprint(int c) { return (c >= 32 && c <= 126); }
int ispunct(int c) { return isgraph(c) && !isalnum(c); }

/*
 * Case conversion
 */
int toupper(int c) { return islower(c) ? c - 32 : c; }
int tolower(int c) { return isupper(c) ? c + 32 : c; }

/*
 * String to integer
 */
int atoi(const char *s) {
    return (int)strtol(s, NULL, 10);
}

/*
 * String to long
 */
long atol(const char *s) {
    return strtol(s, NULL, 10);
}

/*
 * String to long long
 */
long long atoll(const char *s) {
    return strtoll(s, NULL, 10);
}

/*
 * String to long with base detection
 */
long strtol(const char *s, char **endptr, int base) {
    unsigned long result = 0;
    int sign = 1;

    /* Skip whitespace */
    while (isspace(*s)) s++;

    /* Handle sign */
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') s++;

    /* Auto-detect base */
    if (base == 0) {
        if (*s == '0') {
            s++;
            if (*s == 'x' || *s == 'X') { base = 16; s++; }
            else base = 8;
        } else {
            base = 10;
        }
    } else if (base == 16 && *s == '0' && (s[1] == 'x' || s[1] == 'X')) {
        s += 2;
    }

    /* Convert digits */
    while (*s) {
        int digit;
        if (isdigit(*s)) digit = *s - '0';
        else if (*s >= 'a' && *s <= 'f') digit = *s - 'a' + 10;
        else if (*s >= 'A' && *s <= 'F') digit = *s - 'A' + 10;
        else break;

        if (digit >= base) break;

        result = result * base + digit;
        s++;
    }

    if (endptr) *endptr = (char*)s;
    return (long)(result * sign);
}

/*
 * String to unsigned long
 */
unsigned long strtoul(const char *s, char **endptr, int base) {
    return (unsigned long)strtol(s, endptr, base);
}

/*
 * String to long long
 */
long long strtoll(const char *s, char **endptr, int base) {
    unsigned long long result = 0;
    int sign = 1;

    while (isspace(*s)) s++;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') s++;

    if (base == 0) {
        if (*s == '0') {
            s++;
            if (*s == 'x' || *s == 'X') { base = 16; s++; }
            else base = 8;
        } else {
            base = 10;
        }
    } else if (base == 16 && *s == '0' && (s[1] == 'x' || s[1] == 'X')) {
        s += 2;
    }

    while (*s) {
        int digit;
        if (isdigit(*s)) digit = *s - '0';
        else if (*s >= 'a' && *s <= 'f') digit = *s - 'a' + 10;
        else if (*s >= 'A' && *s <= 'F') digit = *s - 'A' + 10;
        else break;

        if (digit >= base) break;
        result = result * base + digit;
        s++;
    }

    if (endptr) *endptr = (char*)s;
    return (long long)(result * sign);
}

/*
 * String to unsigned long long
 */
unsigned long long strtoull(const char *s, char **endptr, int base) {
    return (unsigned long long)strtoll(s, endptr, base);
}

/*
 * String to unsigned long long with length limit and validation
 */
unsigned long long strtoull_wlen(const char *s, int base, int *ok) {
    char *endptr = NULL;
    unsigned long long result = strtoull(s, &endptr, base);
    if (ok) {
        *ok = (endptr != s && *endptr == '\0');
    }
    return result;
}

/*
 * Error string
 */
static const char *error_strings[] = {
    "Success",
    "Unknown error",
    "Invalid argument",
    "Bad address",
    "Argument list too long",
    "Out of memory",
    "Permission denied",
    "Operation not permitted",
    "Function not implemented",
    "Resource busy",
    "File exists",
    "No such file or directory",
    "Not a directory",
    "Is a directory",
    "Too many open files",
    "File table overflow",
    "Broken pipe",
    "Try again",
    "Interrupted system call",
    "I/O error",
    "No such device",
    "Value too large for data type",
    "Illegal seek",
    "Result too large",
    "Domain error",
    "Resource deadlock avoided",
    "Not a terminal",
    "Timer expired",
    "No data available",
    "Connection reset",
    "Connection refused",
    "Already connected",
    "Protocol not available",
    "Not a socket",
    "Message too long",
    "Address family not supported",
    "Address already in use",
    "Address not available",
    "Network is down",
    "Network unreachable",
    "Host is down",
    "Host unreachable",
    "Cannot send after transport endpoint shutdown",
    "Connection timed out",
    "Transport endpoint not connected",
    "No buffer space",
    "No such device",
    "Directory not empty",
    "Read-only filesystem",
    "File too large",
    "No space left on device",
    "Too many links",
    "File name too long",
    "Disk quota exceeded",
};

char *strerror(int errnum) {
    if (errnum >= 0 && (size_t)errnum < sizeof(error_strings) / sizeof(error_strings[0])) {
        return (char*)error_strings[errnum];
    }
    return (char*)"Unknown error";
}