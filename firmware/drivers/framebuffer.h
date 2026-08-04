/*
 * AinosOS - drivers/framebuffer.h
 * Framebuffer driver declarations
 */

#ifndef AINOS_DRIVERS_FRAMEBUFFER_H
#define AINOS_DRIVERS_FRAMEBUFFER_H

#include <types.h>

/* Framebuffer pixel formats */
typedef enum {
    FB_FORMAT_RGB888 = 0,
    FB_FORMAT_BGR888,
    FB_FORMAT_RGB565,
    FB_FORMAT_ARGB8888,
    FB_FORMAT_INDEXED,
    FB_FORMAT_UNKNOWN
} fb_pixel_format_t;

/* Framebuffer structure */
typedef struct {
    uint64_t physical_addr;
    uint64_t virtual_addr;
    uint32_t width;
    uint32_t height;
    uint32_t pitch;
    uint32_t bpp;
    uint32_t size;
    fb_pixel_format_t format;
    int initialized;

    /* Color masks */
    uint32_t red_mask;
    uint32_t green_mask;
    uint32_t blue_mask;
    uint8_t red_shift;
    uint8_t green_shift;
    uint8_t blue_shift;
} framebuffer_t;

/* Framebuffer functions */
int  framebuffer_init(framebuffer_t *fb, uint64_t phys_addr, uint32_t width,
                       uint32_t height, uint32_t pitch, uint32_t bpp);
void framebuffer_clear(framebuffer_t *fb, uint32_t color);
void framebuffer_put_pixel(framebuffer_t *fb, uint32_t x, uint32_t y, uint32_t color);
uint32_t framebuffer_get_pixel(framebuffer_t *fb, uint32_t x, uint32_t y);
void framebuffer_fill_rect(framebuffer_t *fb, uint32_t x, uint32_t y,
                            uint32_t w, uint32_t h, uint32_t color);
void framebuffer_draw_char(framebuffer_t *fb, char c, uint32_t x, uint32_t y,
                            uint32_t fg, uint32_t bg);
void framebuffer_draw_string(framebuffer_t *fb, const char *s, uint32_t x,
                              uint32_t y, uint32_t fg, uint32_t bg);
void framebuffer_draw_line(framebuffer_t *fb, int x0, int y0, int x1, int y1,
                            uint32_t color);
void framebuffer_draw_circle(framebuffer_t *fb, int cx, int cy, int r,
                              uint32_t color);
void framebuffer_blit(framebuffer_t *fb, const void *data, uint32_t x,
                       uint32_t y, uint32_t w, uint32_t h);
uint32_t framebuffer_make_color(framebuffer_t *fb, uint8_t r, uint8_t g, uint8_t b);
void framebuffer_put_char(framebuffer_t *fb, char c, uint32_t x, uint32_t y,
                           uint32_t fg, uint32_t bg);
void framebuffer_scroll(framebuffer_t *fb, int lines);

/* 8x16 built-in font */
extern const uint8_t font8x16[128][16];

/* Color constants */
#define FB_COLOR_BLACK      0x000000
#define FB_COLOR_WHITE      0xFFFFFF
#define FB_COLOR_RED        0xFF0000
#define FB_COLOR_GREEN      0x00FF00
#define FB_COLOR_BLUE       0x0000FF
#define FB_COLOR_YELLOW     0xFFFF00
#define FB_COLOR_CYAN       0x00FFFF
#define FB_COLOR_MAGENTA    0xFF00FF
#define FB_COLOR_GRAY       0x888888
#define FB_COLOR_ORANGE     0xFF8800
#define FB_COLOR_DARK       0x222222

/* Global framebuffer */
extern framebuffer_t g_framebuffer;

#endif /* AINOS_DRIVERS_FRAMEBUFFER_H */