/*
 * AinosOS - drivers/keyboard.c
 * PS/2 keyboard driver implementation
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/io.h>
#include <drivers/keyboard.h>

/* Global keyboard state */
keyboard_state_t g_keyboard_state = { 0 };

/* US keyboard layout scancode -> ASCII (set 1, make codes) */
static const uint8_t scancode_to_ascii_table[128] = {
    0,   27,   '1', '2', '3', '4', '5', '6',   /* 0-7 */
    '7', '8', '9', '0', '-', '=', '\b', '\t',  /* 8-15 */
    'q', 'w', 'e', 'r', 't', 'y', 'u', 'i',   /* 16-23 */
    'o', 'p', '[', ']', '\n', 0,   'a', 's',  /* 24-31 */
    'd', 'f', 'g', 'h', 'j', 'k', 'l', ';',   /* 32-39 */
    '\'', '`', 0,   '\\', 'z', 'x', 'c', 'v',  /* 40-47 */
    'b', 'n', 'm', ',', '.', '/', 0,   '*',   /* 48-55 */
    0,   ' ', 0,   0,   0,   0,   0,   0,      /* 56-63 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 64-71 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 72-79 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 80-87 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 88-95 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 96-103 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 104-111 */
    0,   0,   0,   0,   0,   0,   0,   0,      /* 112-119 */
    0,   0,   0,   0,   0,   0,   0,   0       /* 120-127 */
};

/* US keyboard layout shifted */
static const uint8_t scancode_to_ascii_shift[128] = {
    0,   27,   '!', '@', '#', '$', '%', '^',   /* 0-7 */
    '&', '*', '(', ')', '_', '+', '\b', '\t',  /* 8-15 */
    'Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I',   /* 16-23 */
    'O', 'P', '{', '}', '\n', 0,   'A', 'S',  /* 24-31 */
    'D', 'F', 'G', 'H', 'J', 'K', 'L', ':',   /* 32-39 */
    '"', '~', 0,   '|', 'Z', 'X', 'C', 'V',   /* 40-47 */
    'B', 'N', 'M', '<', '>', '?', 0,   '*',   /* 48-55 */
    0,   ' ', 0,   0,   0,   0,   0,   0,      /* 56-63 */
};

/*
 * Wait for keyboard output buffer to be ready for reading
 */
int keyboard_wait_output(void) {
    for (int timeout = 0; timeout < 10000; timeout++) {
        if (io_inb(KEYBOARD_STATUS_PORT) & KEYBOARD_STATUS_OUTPUT) {
            return 0;
        }
    }
    return -1;  /* Timeout */
}

/*
 * Wait for keyboard input buffer to be empty
 */
int keyboard_wait_input(void) {
    for (int timeout = 0; timeout < 10000; timeout++) {
        if (!(io_inb(KEYBOARD_STATUS_PORT) & KEYBOARD_STATUS_INPUT)) {
            return 0;
        }
    }
    return -1;  /* Timeout */
}

/*
 * Send a command to the keyboard controller
 */
void keyboard_send_command(uint8_t cmd) {
    if (keyboard_wait_input() == 0) {
        io_outb(KEYBOARD_COMMAND_PORT, cmd);
    }
}

/*
 * Send data to the keyboard
 */
void keyboard_send_data(uint8_t data) {
    if (keyboard_wait_input() == 0) {
        io_outb(KEYBOARD_DATA_PORT, data);
    }
}

/*
 * Read a scancode from the keyboard
 */
uint8_t keyboard_read_scancode(void) {
    if (keyboard_wait_output() == 0) {
        return io_inb(KEYBOARD_DATA_PORT);
    }
    return 0;
}

/*
 * Initialize the PS/2 keyboard
 */
int keyboard_init(void) {
    boot_printf(BOOT_LOG_INIT "Initializing PS/2 keyboard...\n");

    g_keyboard_state.initialized = 0;
    g_keyboard_state.modifiers = 0;
    g_keyboard_state.led_state = 0;
    g_keyboard_state.event_head = 0;
    g_keyboard_state.event_tail = 0;

    /* Disable keyboard */
    keyboard_send_command(0xAD);
    keyboard_send_command(0xA7);

    /* Flush output buffer */
    while (io_inb(KEYBOARD_STATUS_PORT) & KEYBOARD_STATUS_OUTPUT) {
        io_inb(KEYBOARD_DATA_PORT);
    }

    /* Enable keyboard */
    keyboard_send_command(0xAE);

    /* Reset keyboard */
    keyboard_send_data(KEYBOARD_CMD_RESET);

    /* Wait for ACK */
    if (keyboard_wait_output() == 0) {
        uint8_t ack = io_inb(KEYBOARD_DATA_PORT);
        if (ack == KEYBOARD_BAT_OK) {
            /* BAT (Basic Assurance Test) passed */
            boot_printf(BOOT_LOG_OK "Keyboard BAT passed\n");
        } else if (ack == KEYBOARD_ACK) {
            boot_printf(BOOT_LOG_OK "Keyboard reset acknowledged\n");
        } else {
            boot_printf(BOOT_LOG_WARN "Keyboard reset returned 0x%02X\n", ack);
        }
    }

    /* Set scancode set 1 */
    keyboard_send_data(KEYBOARD_CMD_SCANCODE_SET);
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* Read ACK */

    keyboard_send_data(0x01);  /* Set 1 */
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* Read ACK */

    g_keyboard_state.scan_code_set = 1;

    /* Enable scanning */
    keyboard_send_data(KEYBOARD_CMD_ENABLE_SCAN);
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* Read ACK */

    /* Set LEDs */
    keyboard_set_leds(0);

    g_keyboard_state.initialized = 1;
    boot_printf(BOOT_LOG_OK "Keyboard initialized\n");

    return 0;
}

/*
 * Convert scancode to ASCII character
 */
char keyboard_scancode_to_ascii(uint8_t scancode, uint16_t modifiers) {
    if (scancode >= 128) return 0;

    if (modifiers & (KEY_MOD_LSHIFT | KEY_MOD_RSHIFT)) {
        char c = scancode_to_ascii_shift[scancode];
        if (c) return c;
    }

    char c = scancode_to_ascii_table[scancode];
    if (c && (modifiers & KEY_MOD_CAPSLOCK) && (c >= 'a' && c <= 'z')) {
        return c - 32;  /* Uppercase */
    }

    return c;
}

/*
 * Set keyboard LEDs
 */
void keyboard_set_leds(uint8_t leds) {
    keyboard_send_data(KEYBOARD_CMD_SET_LEDS);
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* ACK */
    keyboard_send_data(leds & 0x07);
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* ACK */
    g_keyboard_state.led_state = leds & 0x07;
}

/*
 * Keyboard interrupt handler
 */
void keyboard_irq_handler(void) {
    uint8_t status = io_inb(KEYBOARD_STATUS_PORT);

    /* Check if data is available */
    if (!(status & KEYBOARD_STATUS_OUTPUT)) {
        return;
    }

    uint8_t scancode = io_inb(KEYBOARD_DATA_PORT);
    key_event_t event;
    event.scancode = scancode;
    event.pressed = 1;
    event.modifiers = g_keyboard_state.modifiers;
    event.ascii = 0;

    /* Handle make/break codes */
    if (scancode & 0x80) {
        /* Break code (key released) */
        event.pressed = 0;
        scancode &= 0x7F;
        event.scancode = scancode;
    }

    /* Update modifiers */
    switch (scancode) {
        case 0x2A: /* LShift */
            if (event.pressed) g_keyboard_state.modifiers |= KEY_MOD_LSHIFT;
            else g_keyboard_state.modifiers &= ~KEY_MOD_LSHIFT;
            break;
        case 0x36: /* RShift */
            if (event.pressed) g_keyboard_state.modifiers |= KEY_MOD_RSHIFT;
            else g_keyboard_state.modifiers &= ~KEY_MOD_RSHIFT;
            break;
        case 0x1D: /* L/R Ctrl */
            if (event.pressed) g_keyboard_state.modifiers |= KEY_MOD_LCTRL;
            else g_keyboard_state.modifiers &= ~KEY_MOD_LCTRL;
            break;
        case 0x38: /* L/R Alt */
            if (event.pressed) g_keyboard_state.modifiers |= KEY_MOD_LALT;
            else g_keyboard_state.modifiers &= ~KEY_MOD_LALT;
            break;
        case 0x3A: /* CapsLock */
            if (event.pressed) {
                g_keyboard_state.modifiers ^= KEY_MOD_CAPSLOCK;
                keyboard_set_leds(g_keyboard_state.led_state ^ 0x04);
            }
            break;
        case 0x45: /* NumLock */
            if (event.pressed) {
                g_keyboard_state.modifiers ^= KEY_MOD_NUMLOCK;
                keyboard_set_leds(g_keyboard_state.led_state ^ 0x02);
            }
            break;
        case 0x46: /* ScrollLock */
            if (event.pressed) {
                g_keyboard_state.modifiers ^= KEY_MOD_SCROLLLOCK;
                keyboard_set_leds(g_keyboard_state.led_state ^ 0x01);
            }
            break;
    }

    event.modifiers = g_keyboard_state.modifiers;

    /* Convert scancode to ASCII */
    event.ascii = keyboard_scancode_to_ascii(scancode, g_keyboard_state.modifiers);

    /* Add to event buffer */
    int next = (g_keyboard_state.event_head + 1) % 64;
    if (next != g_keyboard_state.event_tail) {
        g_keyboard_state.event_buffer[g_keyboard_state.event_head] = event;
        g_keyboard_state.event_head = next;
    }

    /* Call callback if registered */
    if (g_keyboard_state.callback) {
        g_keyboard_state.callback(&event);
    }
}

/*
 * Set keyboard event callback
 */
void keyboard_set_callback(keyboard_callback_t cb) {
    g_keyboard_state.callback = cb;
}

/*
 * Read next keyboard event (non-blocking)
 */
key_event_t keyboard_read_event(void) {
    key_event_t empty = { 0, 0, 0, 0 };
    if (g_keyboard_state.event_head == g_keyboard_state.event_tail) {
        return empty;
    }

    key_event_t event = g_keyboard_state.event_buffer[g_keyboard_state.event_tail];
    g_keyboard_state.event_tail = (g_keyboard_state.event_tail + 1) % 64;
    return event;
}

/*
 * Check if keyboard events are available
 */
int keyboard_event_available(void) {
    return g_keyboard_state.event_head != g_keyboard_state.event_tail;
}

/*
 * Reset keyboard
 */
void keyboard_reset(void) {
    keyboard_send_data(KEYBOARD_CMD_RESET);
    keyboard_wait_output();
    io_inb(KEYBOARD_DATA_PORT);  /* ACK */
    g_keyboard_state.modifiers = 0;
}