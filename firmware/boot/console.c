/*
 * AinosOS - boot/console.c
 * Early boot console (VGA text mode and serial)
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/io.h>

/* VGA text mode buffer */
#define VGA_BUFFER          0xB8000
#define VGA_WIDTH           80
#define VGA_HEIGHT          25

/* Default VGA colors */
#define VGA_COLOR_BLACK     0
#define VGA_COLOR_BLUE      1
#define VGA_COLOR_GREEN     2
#define VGA_COLOR_CYAN      3
#define VGA_COLOR_RED       4
#define VGA_COLOR_MAGENTA   5
#define VGA_COLOR_BROWN     6
#define VGA_COLOR_LIGHT_GREY  7
#define VGA_COLOR_DARK_GREY   8
#define VGA_COLOR_LIGHT_BLUE  9
#define VGA_COLOR_LIGHT_GREEN 10
#define VGA_COLOR_LIGHT_CYAN  11
#define VGA_COLOR_LIGHT_RED   12
#define VGA_COLOR_LIGHT_MAGENTA 13
#define VGA_COLOR_LIGHT_BROWN  14
#define VGA_COLOR_WHITE      15

/* Make a VGA color byte */
#define VGA_COLOR(fg, bg)   ((fg) | ((bg) << 4))
#define VGA_ENTRY(c, color) ((uint16_t)((uint16_t)(c) | ((uint16_t)(color) << 8)))

/* Default color scheme */
#define DEFAULT_COLOR VGA_COLOR(VGA_COLOR_WHITE, VGA_COLOR_BLACK)
#define ERROR_COLOR   VGA_COLOR(VGA_COLOR_RED, VGA_COLOR_BLACK)
#define OK_COLOR      VGA_COLOR(VGA_COLOR_LIGHT_GREEN, VGA_COLOR_BLACK)
#define WARN_COLOR    VGA_COLOR(VGA_COLOR_LIGHT_BROWN, VGA_COLOR_BLACK)
#define INFO_COLOR    VGA_COLOR(VGA_COLOR_LIGHT_CYAN, VGA_COLOR_BLACK)

/* COM1 serial port */
#define SERIAL_PORT_COM1   0x3F8
#define SERIAL_PORT_COM2   0x2F8

/* Console state */
static volatile uint16_t *vga_buffer = (uint16_t*)VGA_BUFFER;
static int cursor_x = 0;
static int cursor_y = 0;
static uint8_t console_color = DEFAULT_COLOR;
static int serial_enabled = 0;
static int framebuffer_console = 0;

/* Framebuffer console state */
static uint64_t fb_addr = 0;
static uint32_t fb_width = 0;
static uint32_t fb_height = 0;
static uint32_t fb_pitch = 0;
static uint32_t fb_bpp = 0;

/*
 * Initialize the serial port
 */
static int serial_init(uint16_t port) {
    /* Set baud rate (115200 / 9600 = 12) */
    io_outb(port + 1, 0x00);  /* Disable interrupts */
    io_outb(port + 3, 0x80);  /* Enable DLAB */
    io_outb(port + 0, 0x0C);  /* Divisor low: 12 -> 9600 baud */
    io_outb(port + 1, 0x00);  /* Divisor high */
    io_outb(port + 3, 0x03);  /* 8N1: 8 bits, no parity, 1 stop bit */
    io_outb(port + 2, 0xC7);  /* Enable FIFO, clear, 14-byte threshold */
    io_outb(port + 4, 0x0B);  /* IRQ enabled, RTS/DSR set */

    /* Check if serial port is present (loopback test) */
    io_outb(port + 4, 0x1E);  /* Set loopback mode */
    io_outb(port + 0, 0xAE);  /* Send test byte */
    if (io_inb(port + 0) != 0xAE) {
        return 0;  /* No serial port */
    }

    /* Restore normal mode */
    io_outb(port + 4, 0x0F);
    io_outb(port + 1, 0x00);  /* Disable all interrupts */

    return 1;
}

/*
 * Write a byte to serial port
 */
static void serial_putchar(uint16_t port, char c) {
    /* Wait for transmitter holding register to be empty */
    for (int i = 0; i < 10000; i++) {
        if (io_inb(port + 5) & 0x20) {
            break;
        }
    }
    io_outb(port, c);

    /* Handle LF -> CRLF for serial */
    if (c == '\n') {
        for (int i = 0; i < 10000; i++) {
            if (io_inb(port + 5) & 0x20) {
                break;
            }
        }
        io_outb(port, '\r');
    }
}

/*
 * Initialize the boot console
 * Sets up VGA text mode and serial
 */
void boot_console_init(void) {
    /* Clear VGA screen */
    for (int y = 0; y < VGA_HEIGHT; y++) {
        for (int x = 0; x < VGA_WIDTH; x++) {
            vga_buffer[y * VGA_WIDTH + x] = VGA_ENTRY(' ', DEFAULT_COLOR);
        }
    }

    /* Reset cursor */
    cursor_x = 0;
    cursor_y = 0;

    /* Try to initialize serial */
    serial_enabled = serial_init(SERIAL_PORT_COM1);
    if (!serial_enabled) {
        serial_enabled = serial_init(SERIAL_PORT_COM2);
    }
}

/*
 * Set the framebuffer console parameters
 */
void boot_console_set_framebuffer(uint64_t addr, uint32_t width,
                                   uint32_t height, uint32_t pitch,
                                   uint32_t bpp) {
    fb_addr = addr;
    fb_width = width;
    fb_height = height;
    fb_pitch = pitch;
    fb_bpp = bpp;
    framebuffer_console = 1;
}

/*
 * Scroll the VGA console up by one line
 */
static void console_scroll(void) {
    /* Move all lines up */
    for (int y = 0; y < VGA_HEIGHT - 1; y++) {
        for (int x = 0; x < VGA_WIDTH; x++) {
            vga_buffer[y * VGA_WIDTH + x] = vga_buffer[(y + 1) * VGA_WIDTH + x];
        }
    }

    /* Clear the bottom line */
    for (int x = 0; x < VGA_WIDTH; x++) {
        vga_buffer[(VGA_HEIGHT - 1) * VGA_WIDTH + x] = VGA_ENTRY(' ', console_color);
    }

    cursor_y = VGA_HEIGHT - 1;
}

/*
 * Write a character to the VGA console
 */
static void vga_putchar(char c) {
    switch (c) {
        case '\n':
            cursor_x = 0;
            cursor_y++;
            break;

        case '\r':
            cursor_x = 0;
            break;

        case '\t':
            /* Tab: advance to next 8-column boundary */
            do {
                vga_buffer[cursor_y * VGA_WIDTH + cursor_x] = VGA_ENTRY(' ', console_color);
                cursor_x++;
            } while (cursor_x < VGA_WIDTH && (cursor_x % 8) != 0);
            break;

        case '\b':
            if (cursor_x > 0) {
                cursor_x--;
                vga_buffer[cursor_y * VGA_WIDTH + cursor_x] = VGA_ENTRY(' ', console_color);
            }
            break;

        default:
            if (c >= 32 && c < 127) {
                vga_buffer[cursor_y * VGA_WIDTH + cursor_x] = VGA_ENTRY(c, console_color);
                cursor_x++;
            }
            break;
    }

    /* Handle line wrapping */
    if (cursor_x >= VGA_WIDTH) {
        cursor_x = 0;
        cursor_y++;
    }

    /* Handle scrolling */
    if (cursor_y >= VGA_HEIGHT) {
        console_scroll();
    }

    /* Update hardware cursor */
    uint16_t pos = cursor_y * VGA_WIDTH + cursor_x;
    io_outb(0x3D4, 0x0F);
    io_outb(0x3D5, (uint8_t)(pos & 0xFF));
    io_outb(0x3D4, 0x0E);
    io_outb(0x3D5, (uint8_t)((pos >> 8) & 0xFF));
}

/*
 * Draw a pixel on the framebuffer
 */
static void fb_put_pixel(uint32_t x, uint32_t y, uint32_t color) {
    if (x >= fb_width || y >= fb_height) return;

    uint8_t *ptr = (uint8_t*)(uint64_t)fb_addr + y * fb_pitch + x * (fb_bpp / 8);
    *(uint32_t*)ptr = color;
}

/*
 * Draw a character on the framebuffer (simple 8x16 bitmap font)
 * This is a basic implementation using a simple built-in font
 */
static void fb_putchar(char c, uint32_t x, uint32_t y, uint32_t fg, uint32_t bg) {
    /* Simple 8x16 font data for ASCII characters 32-127 */
    /* Each character is 16 bytes, each byte represents 8 pixels */
    static const uint8_t font8x16[128][16] = {
        /* 0x20 (space) */
        {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
        /* 0x21 (!) */
        {0x00,0x00,0x18,0x3C,0x3C,0x3C,0x18,0x18,0x18,0x00,0x18,0x18,0x00,0x00,0x00,0x00},
        /* 0x22 (") */
        {0x00,0x00,0x66,0x66,0x66,0x24,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
        /* 0x23 (#) */
        {0x00,0x00,0x00,0x24,0x24,0x7E,0x24,0x24,0x24,0x7E,0x24,0x24,0x00,0x00,0x00,0x00},
        /* 0x24 ($) */
        {0x00,0x08,0x3E,0x49,0x48,0x38,0x0E,0x09,0x49,0x3E,0x08,0x00,0x00,0x00,0x00,0x00},
        /* 0x25 (%) */
        {0x00,0x00,0x31,0x4A,0x4A,0x34,0x08,0x08,0x2C,0x52,0x52,0x4C,0x00,0x00,0x00,0x00},
        /* 0x26 (&) */
        {0x00,0x00,0x1C,0x22,0x22,0x1C,0x38,0x55,0x4A,0x42,0x22,0x5C,0x00,0x00,0x00,0x00},
        /* 0x27 (') */
        {0x00,0x00,0x18,0x18,0x18,0x30,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00},
        /* 0x28 (() */
        {0x00,0x00,0x04,0x08,0x10,0x10,0x10,0x10,0x10,0x10,0x08,0x04,0x00,0x00,0x00,0x00},
        /* 0x29 ()) */
        {0x00,0x00,0x20,0x10,0x08,0x08,0x08,0x08,0x08,0x08,0x10,0x20,0x00,0x00,0x00,0x00},
        /* Rest of characters would be here - for brevity we use a minimal set */
    };

    if ((unsigned char)c < 32 || (unsigned char)c > 126) {
        c = ' ';
    }

    const uint8_t *glyph = font8x16[(unsigned char)c];
    for (int row = 0; row < 16; row++) {
        for (int col = 0; col < 8; col++) {
            if (glyph[row] & (1 << (7 - col))) {
                fb_put_pixel(x + col, y + row, fg);
            } else {
                fb_put_pixel(x + col, y + row, bg);
            }
        }
    }
}

/*
 * Write a character to the console (both VGA and serial)
 */
void boot_putchar(char c) {
    /* Write to VGA */
    vga_putchar(c);

    /* Write to serial */
    if (serial_enabled) {
        serial_putchar(SERIAL_PORT_COM1, c);
    }
}

/*
 * Write a string to the console
 */
void boot_puts(const char *s) {
    while (s && *s) {
        boot_putchar(*s++);
    }
}

/*
 * Set console color
 */
void boot_console_set_color(uint8_t fg, uint8_t bg) {
    console_color = VGA_COLOR(fg, bg);
}

/*
 * Clear the console
 */
void boot_console_clear(void) {
    for (int y = 0; y < VGA_HEIGHT; y++) {
        for (int x = 0; x < VGA_WIDTH; x++) {
            vga_buffer[y * VGA_WIDTH + x] = VGA_ENTRY(' ', DEFAULT_COLOR);
        }
    }
    cursor_x = 0;
    cursor_y = 0;
}

/*
 * Get cursor position
 */
void boot_console_get_cursor(int *x, int *y) {
    *x = cursor_x;
    *y = cursor_y;
}

/*
 * Set cursor position
 */
void boot_console_set_cursor(int x, int y) {
    if (x >= 0 && x < VGA_WIDTH) cursor_x = x;
    if (y >= 0 && y < VGA_HEIGHT) cursor_y = y;
}

/*
 * Write a character with color
 */
void boot_console_putchar_color(char c, uint8_t fg, uint8_t bg) {
    uint8_t old_fg = console_color & 0x0F;
    uint8_t old_bg = (console_color >> 4) & 0x0F;
    console_color = VGA_COLOR(fg, bg);
    boot_putchar(c);
    console_color = VGA_COLOR(old_fg, old_bg);
}

/*
 * Write a string with color
 */
void boot_console_puts_color(const char *s, uint8_t fg, uint8_t bg) {
    uint8_t old_fg = console_color & 0x0F;
    uint8_t old_bg = (console_color >> 4) & 0x0F;
    console_color = VGA_COLOR(fg, bg);
    boot_puts(s);
    console_color = VGA_COLOR(old_fg, old_bg);
}

/*
 * Read a character from serial (non-blocking, returns -1 if no data)
 */
int boot_serial_read(void) {
    if (serial_enabled && (io_inb(SERIAL_PORT_COM1 + 5) & 1)) {
        return io_inb(SERIAL_PORT_COM1);
    }
    return -1;
}