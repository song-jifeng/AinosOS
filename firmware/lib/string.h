/*
 * AinosOS - lib/string.h
 * String and memory function declarations
 */

#ifndef AINOS_LIB_STRING_H
#define AINOS_LIB_STRING_H

#include <types.h>

/* Memory operations */
void *memset(void *s, int c, size_t n);
void *memcpy(void *dest, const void *src, size_t n);
void *memmove(void *dest, const void *src, size_t n);
int memcmp(const void *s1, const void *s2, size_t n);
void *memchr(const void *s, int c, size_t n);
void *memrchr(const void *s, int c, size_t n);
void *memccpy(void *dest, const void *src, int c, size_t n);
void *memmem(const void *haystack, size_t hlen, const void *needle, size_t nlen);
void bzero(void *s, size_t n);

/* String operations */
size_t strlen(const char *s);
size_t strnlen(const char *s, size_t maxlen);
char *strcpy(char *dest, const char *src);
char *strncpy(char *dest, const char *src, size_t n);
char *strcat(char *dest, const char *src);
char *strncat(char *dest, const char *src, size_t n);
int strcmp(const char *s1, const char *s2);
int strncmp(const char *s1, const char *s2, size_t n);
int strcasecmp(const char *s1, const char *s2);
int strncasecmp(const char *s1, const char *s2, size_t n);
char *strchr(const char *s, int c);
char *strrchr(const char *s, int c);
char *strstr(const char *haystack, const char *needle);
char *strpbrk(const char *s, const char *accept);
size_t strspn(const char *s, const char *accept);
size_t strcspn(const char *s, const char *reject);
char *strtok(char *str, const char *delim);
char *strtok_r(char *str, const char *delim, char **saveptr);
char *strdup(const char *s);
char *strndup(const char *s, size_t n);
char *strerror(int errnum);
void *malloc(size_t size);
void free(void *ptr);

/* Character classification */
int isalpha(int c);
int isdigit(int c);
int isalnum(int c);
int isspace(int c);
int isupper(int c);
int islower(int c);
int isxdigit(int c);
int iscntrl(int c);
int isgraph(int c);
int isprint(int c);
int ispunct(int c);
int toupper(int c);
int tolower(int c);

/* String to number conversions */
int atoi(const char *s);
long atol(const char *s);
long long atoll(const char *s);
long strtol(const char *s, char **endptr, int base);
unsigned long strtoul(const char *s, char **endptr, int base);
long long strtoll(const char *s, char **endptr, int base);
unsigned long long strtoull(const char *s, char **endptr, int base);
unsigned long long strtoull_wlen(const char *s, int base, int *ok);

#endif /* AINOS_LIB_STRING_H */