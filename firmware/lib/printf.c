/*
 * AinosOS - lib/printf.c
 * Formatted output implementation (printf family)
 *
 * Supports: %d, %i, %u, %x, %X, %p, %s, %c, %llu, %llx, %lld, %ld, %lu,
 *           %o, %b, %f (basic), %n, width, precision, zero-padding, flags
 */

#include <types.h>
#include <lib/string.h>
#include <stdarg.h>

/* Current output function */
static printf_putchar_t g_putchar = NULL;

/* Buffer for sprintf/snprintf */
struct printf_buf {
    char *buf;
    size_t size;
    size_t pos;
};

/*
 * Set the output function
 */
void printf_set_output(printf_putchar_t putchar_func) {
    g_putchar = putchar_func;
}

/*
 * Write a character to the output function
 */
static void out_char(char c) {
    if (g_putchar) {
        g_putchar(c);
    }
}

/*
 * Write a character to a buffer (for sprintf)
 */
static void buf_char(struct printf_buf *buf, char c) {
    if (buf->pos < buf->size - 1) {
        buf->buf[buf->pos++] = c;
    }
}

/*
 * Write a string directly
 */
static void out_str(const char *s) {
    while (*s) out_char(*s++);
}

/*
 * Pad with a character
 */
static void pad_char(int count, char c) {
    for (int i = 0; i < count; i++) {
        out_char(c);
    }
}

/*
 * Buffer padding
 */
static void buf_pad(struct printf_buf *buf, int count, char c) {
    for (int i = 0; i < count; i++) {
        buf_char(buf, c);
    }
}

/*
 * Convert unsigned long long to string (base up to 36)
 */
static char *ultoa(unsigned long long value, char *str, int base, int uppercase) {
    static const char digits_lower[] = "0123456789abcdefghijklmnopqrstuvwxyz";
    static const char digits_upper[] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const char *digits = uppercase ? digits_upper : digits_lower;
    char *p = str;
    char *start = str;

    if (value == 0) {
        *p++ = '0';
    } else {
        while (value > 0) {
            *p++ = digits[value % base];
            value /= base;
        }
    }
    *p-- = '\0';

    /* Reverse the string */
    while (p > start) {
        char tmp = *p;
        *p-- = *start;
        *start++ = tmp;
    }

    return str;
}

/*
 * Core formatting engine
 */
static int format_core(const char *fmt, va_list args, struct printf_buf *buf) {
    char num_buf[65];
    int count = 0;
    int use_buf = (buf != NULL);

    /* Set up output function */
    if (use_buf) {
        buf->pos = 0;
        buf->buf[0] = '\0';
    }

    /* Define output macros based on mode */
    #define PUTCHAR(c) do { \
        if (use_buf) { buf_char(buf, c); } \
        else { out_char(c); } \
        count++; \
    } while(0)

    #define PUTSTR(s) do { \
        const char *_p = (s); \
        while (*_p) PUTCHAR(*_p++); \
    } while(0)

    #define PAD(n, c) do { \
        int _n = (n); \
        if (_n > 0) { \
            if (use_buf) { buf_pad(buf, _n, c); } \
            else { pad_char(_n, c); } \
            count += _n; \
        } \
    } while(0)

    while (*fmt) {
        if (*fmt != '%') {
            PUTCHAR(*fmt++);
            continue;
        }

        fmt++;  /* Skip '%' */

        /* Parse flags */
        int flags = 0;
        #define FLAG_MINUS  1
        #define FLAG_PLUS   2
        #define FLAG_SPACE  4
        #define FLAG_ZERO   8
        #define FLAG_HASH   16

        int parsing_flags = 1;
        while (parsing_flags) {
            switch (*fmt) {
                case '-': flags |= FLAG_MINUS; fmt++; break;
                case '+': flags |= FLAG_PLUS; fmt++; break;
                case ' ': flags |= FLAG_SPACE; fmt++; break;
                case '0': flags |= FLAG_ZERO; fmt++; break;
                case '#': flags |= FLAG_HASH; fmt++; break;
                default: parsing_flags = 0; break;
            }
        }

        /* Parse width */
        int width = 0;
        if (*fmt == '*') {
            width = va_arg(args, int);
            if (width < 0) {
                width = -width;
                flags |= FLAG_MINUS;
            }
            fmt++;
        } else {
            while (*fmt >= '0' && *fmt <= '9') {
                width = width * 10 + (*fmt++ - '0');
            }
        }

        /* Parse precision */
        int precision = -1;
        if (*fmt == '.') {
            fmt++;
            if (*fmt == '*') {
                precision = va_arg(args, int);
                fmt++;
            } else {
                precision = 0;
                while (*fmt >= '0' && *fmt <= '9') {
                    precision = precision * 10 + (*fmt++ - '0');
                }
            }
        }

        /* Parse length modifiers */
        int is_long = 0;
        int is_long_long = 0;
        int is_short = 0;
        int is_size = 0;
        int is_intmax = 0;

        if (*fmt == 'l') {
            fmt++;
            if (*fmt == 'l') {
                is_long_long = 1;
                fmt++;
            } else {
                is_long = 1;
            }
        } else if (*fmt == 'h') {
            fmt++;
            if (*fmt == 'h') {
                is_short = 2;  /* char */
                fmt++;
            } else {
                is_short = 1;  /* short */
            }
        } else if (*fmt == 'z') {
            is_size = 1;
            fmt++;
        } else if (*fmt == 'j') {
            is_intmax = 1;
            fmt++;
        } else if (*fmt == 't') {
            is_long_long = 1;  /* ptrdiff_t = long long on 64-bit */
            fmt++;
        }

        /* Parse conversion specifier */
        char spec = *fmt++;
        unsigned long long num_val = 0;
        int num_negative = 0;
        char *str_val = NULL;
        int int_val = 0;
        int base = 10;
        int uppercase = 0;

        switch (spec) {
            case 'd':
            case 'i': {
                long long llval;
                if (is_long_long) {
                    llval = va_arg(args, long long);
                } else if (is_long) {
                    llval = va_arg(args, long);
                } else if (is_short == 2) {
                    llval = (signed char)va_arg(args, int);
                } else if (is_short == 1) {
                    llval = (short)va_arg(args, int);
                } else {
                    llval = va_arg(args, int);
                }

                if (llval < 0) {
                    num_negative = 1;
                    num_val = (unsigned long long)(-llval);
                } else {
                    num_val = (unsigned long long)llval;
                }
                base = 10;
                break;
            }

            case 'u': {
                if (is_long_long) {
                    num_val = va_arg(args, unsigned long long);
                } else if (is_long) {
                    num_val = va_arg(args, unsigned long);
                } else if (is_size) {
                    num_val = va_arg(args, size_t);
                } else {
                    num_val = va_arg(args, unsigned int);
                }
                base = 10;
                break;
            }

            case 'x':
                uppercase = 0;
                goto hex_common;
            case 'X':
                uppercase = 1;
                goto hex_common;
            hex_common:
                if (is_long_long) {
                    num_val = va_arg(args, unsigned long long);
                } else if (is_long) {
                    num_val = va_arg(args, unsigned long);
                } else {
                    num_val = va_arg(args, unsigned int);
                }
                base = 16;
                break;

            case 'o':
                if (is_long_long) {
                    num_val = va_arg(args, unsigned long long);
                } else if (is_long) {
                    num_val = va_arg(args, unsigned long);
                } else {
                    num_val = va_arg(args, unsigned int);
                }
                base = 8;
                break;

            case 'b':
                if (is_long_long) {
                    num_val = va_arg(args, unsigned long long);
                } else if (is_long) {
                    num_val = va_arg(args, unsigned long);
                } else {
                    num_val = va_arg(args, unsigned int);
                }
                base = 2;
                break;

            case 'p':
                num_val = (unsigned long long)va_arg(args, void*);
                flags |= FLAG_HASH;
                base = 16;
                break;

            case 's':
                str_val = va_arg(args, char*);
                if (str_val == NULL) str_val = "(null)";
                break;

            case 'c':
                int_val = va_arg(args, int);
                break;

            case 'n': {
                int *n = va_arg(args, int*);
                if (n) *n = count;
                continue;
            }

            case '%':
                PUTCHAR('%');
                continue;

            default:
                PUTCHAR('%');
                PUTCHAR(spec);
                continue;
        }

        /* Format the value */
        if (str_val != NULL) {
            /* String formatting */
            int len = strlen(str_val);
            if (precision >= 0 && precision < len) len = precision;
            int pad = width > len ? width - len : 0;

            if (!(flags & FLAG_MINUS)) PAD(pad, ' ');
            for (int i = 0; i < len; i++) PUTCHAR(str_val[i]);
            if (flags & FLAG_MINUS) PAD(pad, ' ');

        } else if (spec == 'c') {
            /* Character */
            int pad = width > 1 ? width - 1 : 0;
            if (!(flags & FLAG_MINUS)) PAD(pad, ' ');
            PUTCHAR(int_val);
            if (flags & FLAG_MINUS) PAD(pad, ' ');

        } else {
            /* Numeric formatting */
            ultoa(num_val, num_buf, base, uppercase);
            int num_len = strlen(num_buf);

            /* Handle prefix */
            int prefix_len = 0;
            char prefix_char = 0;
            if (num_negative) {
                prefix_char = '-';
                prefix_len = 1;
            } else if (flags & FLAG_PLUS) {
                prefix_char = '+';
                prefix_len = 1;
            } else if (flags & FLAG_SPACE) {
                prefix_char = ' ';
                prefix_len = 1;
            }

            /* Handle alternate form (#) */
            const char *alt_prefix = "";
            int alt_len = 0;
            if ((flags & FLAG_HASH) && num_val != 0) {
                if (base == 16) {
                    alt_prefix = uppercase ? "0X" : "0x";
                    alt_len = 2;
                } else if (base == 8) {
                    alt_prefix = "0";
                    alt_len = 1;
                }
            } else if (spec == 'p') {
                alt_prefix = "0x";
                alt_len = 2;
            }

            /* Handle zero precision with zero value */
            if (precision == 0 && num_val == 0) {
                num_len = 0;
                num_buf[0] = '\0';
            }

            /* Calculate padding */
            int digits = (precision > num_len) ? precision : num_len;
            int total_len = prefix_len + alt_len + digits;
            int pad = width > total_len ? width - total_len : 0;

            /* Zero padding overrides spaces for padding */
            char pad_char = (flags & FLAG_ZERO) && !(flags & FLAG_MINUS) && precision < 0 ? '0' : ' ';

            if (!(flags & FLAG_MINUS) && pad_char == ' ') PAD(pad, ' ');

            /* Output prefix */
            if (prefix_char) PUTCHAR(prefix_char);
            if (alt_len) PUTSTR(alt_prefix);

            /* Zero padding after prefix */
            if (!(flags & FLAG_MINUS) && pad_char == '0') PAD(pad, '0');

            /* Precision padding */
            if (precision > num_len) PAD(precision - num_len, '0');

            /* Number digits */
            PUTSTR(num_buf);

            /* Right padding */
            if (flags & FLAG_MINUS) PAD(pad, ' ');
        }
    }

    /* Null-terminate buffer */
    if (use_buf) {
        buf->buf[buf->pos] = '\0';
    }

    return count;

    #undef PUTCHAR
    #undef PUTSTR
    #undef PAD
}

/*
 * printf - formatted print to current output function
 */
int printf(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    int result = format_core(fmt, args, NULL);
    va_end(args);
    return result;
}

/*
 * vprintf - formatted print with va_list
 */
int vprintf(const char *fmt, va_list args) {
    return format_core(fmt, args, NULL);
}

/*
 * sprintf - formatted print to buffer
 */
int sprintf(char *buf, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    struct printf_buf pb = { buf, (size_t)-1, 0 };
    int result = format_core(fmt, args, &pb);
    va_end(args);
    return result;
}

/*
 * vsprintf - formatted print to buffer with va_list
 */
int vsprintf(char *buf, const char *fmt, va_list args) {
    struct printf_buf pb = { buf, (size_t)-1, 0 };
    return format_core(fmt, args, &pb);
}

/*
 * snprintf - formatted print to buffer with size limit
 */
int snprintf(char *buf, size_t size, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    struct printf_buf pb = { buf, size, 0 };
    int result = format_core(fmt, args, &pb);
    va_end(args);
    return result;
}

/*
 * vsnprintf - formatted print to buffer with va_list and size limit
 */
int vsnprintf(char *buf, size_t size, const char *fmt, va_list args) {
    struct printf_buf pb = { buf, size, 0 };
    return format_core(fmt, args, &pb);
}

/*
 * putchar - write a character to console
 */
void putchar(char c) {
    if (g_putchar) {
        g_putchar(c);
    }
}

/*
 * puts - write a string to console
 */
void puts(const char *s) {
    while (s && *s) {
        putchar(*s++);
    }
    putchar('\n');
}

/*
 * boot_printf - early boot printf using VGA console
 * This is used before the full printf system is initialized
 */
void boot_printf(const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    /* boot_printf directly calls the boot console putchar */
    /* The output function is set during boot initialization */
    vprintf(fmt, args);
    va_end(args);
}