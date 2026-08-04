/*
 * AinosOS - drivers/keyboard.h
 * PS/2 keyboard driver declarations
 */

#ifndef AINOS_DRIVERS_KEYBOARD_H
#define AINOS_DRIVERS_KEYBOARD_H

#include <types.h>

/* PS/2 keyboard port */
#define KEYBOARD_DATA_PORT      0x60
#define KEYBOARD_STATUS_PORT    0x64
#define KEYBOARD_COMMAND_PORT   0x64

/* Keyboard status bits */
#define KEYBOARD_STATUS_OUTPUT  0x01
#define KEYBOARD_STATUS_INPUT   0x02
#define KEYBOARD_STATUS_SYSTEM  0x04
#define KEYBOARD_STATUS_CMD     0x08
#define KEYBOARD_STATUS_TIMEOUT 0x40
#define KEYBOARD_STATUS_PARITY  0x80

/* Keyboard commands */
#define KEYBOARD_CMD_SET_LEDS       0xED
#define KEYBOARD_CMD_ECHO           0xEE
#define KEYBOARD_CMD_SCANCODE_SET   0xF0
#define KEYBOARD_CMD_IDENTIFY       0xF2
#define KEYBOARD_CMD_ENABLE_SCAN    0xF4
#define KEYBOARD_CMD_DISABLE_SCAN   0xF5
#define KEYBOARD_CMD_RESET          0xFF

/* Keyboard responses */
#define KEYBOARD_ACK        0xFA
#define KEYBOARD_RESEND     0xFE
#define KEYBOARD_BAT_OK     0xAA
#define KEYBOARD_ECHO_RESP  0xEE

/* Modifier keys */
#define KEY_MOD_LSHIFT      0x01
#define KEY_MOD_RSHIFT      0x02
#define KEY_MOD_LCTRL       0x04
#define KEY_MOD_RCTRL       0x08
#define KEY_MOD_LALT        0x10
#define KEY_MOD_RALT        0x20
#define KEY_MOD_CAPSLOCK    0x40
#define KEY_MOD_NUMLOCK     0x80
#define KEY_MOD_SCROLLLOCK  0x100

/* Special key codes */
#define KEY_ESC         0x01
#define KEY_BACKSPACE   0x0E
#define KEY_TAB         0x0F
#define KEY_ENTER       0x1C
#define KEY_LCTRL       0x1D
#define KEY_LSHIFT      0x2A
#define KEY_RSHIFT      0x36
#define KEY_LALT        0x38
#define KEY_CAPSLOCK    0x3A
#define KEY_F1          0x3B
#define KEY_F2          0x3C
#define KEY_F3          0x3D
#define KEY_F4          0x3E
#define KEY_F5          0x3F
#define KEY_F6          0x40
#define KEY_F7          0x41
#define KEY_F8          0x42
#define KEY_F9          0x43
#define KEY_F10         0x44
#define KEY_F11         0x57
#define KEY_F12         0x58
#define KEY_NUMLOCK     0x45
#define KEY_SCROLLLOCK  0x46
#define KEY_HOME        0x47
#define KEY_UP          0x48
#define KEY_PAGEUP      0x49
#define KEY_LEFT        0x4B
#define KEY_RIGHT       0x4D
#define KEY_END         0x4F
#define KEY_DOWN        0x50
#define KEY_PAGEDOWN    0x51
#define KEY_INSERT      0x52
#define KEY_DELETE      0x53
#define KEY_PRINTSCREEN 0x37

/* Key press event */
typedef struct {
    uint8_t scancode;
    uint8_t ascii;
    uint16_t modifiers;
    int pressed;    /* 1 = pressed, 0 = released */
} key_event_t;

/* Keyboard callback */
typedef void (*keyboard_callback_t)(key_event_t *event);

/* Keyboard state */
typedef struct {
    int initialized;
    uint16_t modifiers;
    uint8_t led_state;
    int scan_code_set;
    keyboard_callback_t callback;
    key_event_t event_buffer[64];
    int event_head;
    int event_tail;
} keyboard_state_t;

/* Keyboard functions */
int  keyboard_init(void);
void keyboard_set_callback(keyboard_callback_t cb);
void keyboard_irq_handler(void);
key_event_t keyboard_read_event(void);
int  keyboard_event_available(void);
uint8_t keyboard_read_scancode(void);
void keyboard_send_command(uint8_t cmd);
void keyboard_send_data(uint8_t data);
int  keyboard_wait_output(void);
int  keyboard_wait_input(void);
void keyboard_set_leds(uint8_t leds);
void keyboard_reset(void);

/* Scancode to ASCII conversion */
char keyboard_scancode_to_ascii(uint8_t scancode, uint16_t modifiers);

/* Global keyboard state */
extern keyboard_state_t g_keyboard_state;

#endif /* AINOS_DRIVERS_KEYBOARD_H */