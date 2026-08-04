/*
 * AinosOS - lib/printf.h
 * Formatted output function declarations
 */

#ifndef AINOS_LIB_PRINTF_H
#define AINOS_LIB_PRINTF_H

#include <types.h>

/* Type for printf output function */
typedef void (*printf_putchar_t)(char c);

/* Set the output function used by printf */
void printf_set_output(printf_putchar_t putchar_func);

/* printf functions */
int printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
int sprintf(char *buf, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
int snprintf(char *buf, size_t size, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
int vsnprintf(char *buf, size_t size, const char *fmt, va_list args);
int vprintf(const char *fmt, va_list args);
int vsprintf(char *buf, const char *fmt, va_list args);

/* Boot printf (early console) */
void boot_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* Console output function */
void putchar(char c);
void puts(const char *s);

#endif /* AINOS_LIB_PRINTF_H */