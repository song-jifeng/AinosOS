/*
 * AinosOS - drivers/timer.c
 * Timer driver implementation (PIT, HPET)
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/io.h>
#include <arch/x86_64/registers.h>
#include <drivers/timer.h>

/* Global system timer */
timer_device_t g_system_timer = { 0 };

/* PIT timer state */
static uint32_t pit_frequency = 0;

/* HPET base address */
static volatile uint64_t *hpet_base = NULL;
static uint64_t hpet_femto_period = 0;  /* Femtoseconds per tick */

/*
 * Initialize the PIT timer
 */
void pit_init(uint32_t frequency) {
    if (frequency == 0) frequency = 100;  /* Default: 100 Hz */

    uint32_t divisor = PIT_BASE_FREQ / frequency;

    /* Ensure divisor is in valid range */
    if (divisor < 2) divisor = 2;
    if (divisor > 0xFFFF) divisor = 0xFFFF;

    /* Set PIT to square wave mode */
    io_outb(PIT_CMD, PIT_SEL_CH0 | PIT_ACCESS_LH | PIT_MODE3);

    /* Send divisor */
    io_outb(PIT_CH0, divisor & 0xFF);
    io_outb(PIT_CH0, (divisor >> 8) & 0xFF);

    pit_frequency = frequency;
}

/*
 * Set PIT frequency
 */
void pit_set_frequency(uint32_t frequency) {
    pit_init(frequency);
}

/*
 * Set PIT to one-shot mode
 */
void pit_set_one_shot(uint32_t count) {
    io_outb(PIT_CMD, PIT_SEL_CH0 | PIT_ACCESS_LH | PIT_MODE0);
    io_outb(PIT_CH0, count & 0xFF);
    io_outb(PIT_CH0, (count >> 8) & 0xFF);
}

/*
 * Read current PIT counter value
 */
uint32_t pit_read_count(void) {
    io_outb(PIT_CMD, PIT_SEL_CH0 | PIT_ACCESS_LH);
    uint32_t lo = io_inb(PIT_CH0);
    uint32_t hi = io_inb(PIT_CH0);
    return lo | (hi << 8);
}

/*
 * Initialize HPET
 */
int hpet_init(void) {
    /* HPET base address is read from ACPI HPET table */
    /* For now, try to detect HPET at standard memory-mapped address */
    /* In a real system, this comes from ACPI */

    /* Try common HPET base addresses */
    uint64_t possible_bases[] = {
        0xFED00000, 0xFED01000, 0xFED02000, 0xFED03000
    };

    for (int i = 0; i < 4; i++) {
        volatile uint64_t *test_base = (volatile uint64_t*)(uint64_t)possible_bases[i];
        uint64_t cap_id = test_base[0];

        /* Check HPET signature (bits 31:16 = 0x8086 for Intel, 0x4353 for AMD) */
        if ((cap_id & 0xFFFF0000) != 0) {
            hpet_base = test_base;
            hpet_femto_period = cap_id >> 32;
            return 0;
        }
    }

    return -1;  /* HPET not found */
}

/*
 * Start HPET counter
 */
void hpet_start(void) {
    if (!hpet_base) return;
    hpet_base[HPET_GEN_CONF / 8] |= 1;
}

/*
 * Stop HPET counter
 */
void hpet_stop(void) {
    if (!hpet_base) return;
    hpet_base[HPET_GEN_CONF / 8] &= ~1ULL;
}

/*
 * Read HPET main counter
 */
uint64_t hpet_read_counter(void) {
    if (!hpet_base) return 0;
    return hpet_base[HPET_MAIN_CNT / 8];
}

/*
 * Get HPET frequency in Hz
 */
uint64_t hpet_get_frequency(void) {
    if (hpet_femto_period == 0) return 0;
    /* 1 femtosecond = 10^-15, so frequency = 10^15 / period */
    return 1000000000000000ULL / hpet_femto_period;
}

/*
 * Configure an HPET timer
 */
void hpet_set_timer(uint32_t timer_num, uint64_t interval, int periodic) {
    if (!hpet_base || timer_num > 31) return;

    uint32_t timer_conf_offset = HPET_TIMER0_CONF + timer_num * 0x20;
    uint32_t timer_comp_offset = HPET_TIMER0_COMP + timer_num * 0x20;

    uint64_t config = hpet_base[timer_conf_offset / 8];

    /* Set 32-bit mode */
    config |= HPET_TN_32BIT;

    if (periodic) {
        config |= HPET_TN_PERIODIC;
        config |= HPET_TN_SET_ACCUM;
    } else {
        config &= ~HPET_TN_PERIODIC;
    }

    hpet_base[timer_conf_offset / 8] = config;
    hpet_base[timer_comp_offset / 8] = interval;

    /* Enable the timer */
    config |= HPET_TN_ENABLE;
    hpet_base[timer_conf_offset / 8] = config;
}

/*
 * Initialize the system timer
 * Tries HPET first, falls back to PIT
 */
int timer_init(timer_device_t *timer) {
    if (!timer) return -1;

    /* Try HPET first */
    if (hpet_init() == 0) {
        timer->type = TIMER_HPET;
        timer->frequency = hpet_get_frequency();
        hpet_start();
        boot_printf(BOOT_LOG_OK "HPET timer initialized: %llu Hz\n", timer->frequency);
    } else {
        /* Fall back to PIT */
        timer->type = TIMER_PIT;
        pit_init(100);  /* 100 Hz */
        timer->frequency = 100;
        boot_printf(BOOT_LOG_OK "PIT timer initialized: %u Hz\n", pit_frequency);
    }

    timer->initialized = 1;
    timer->ticks = 0;
    timer->uptime_ms = 0;
    g_system_timer = *timer;

    return 0;
}

/*
 * Set timer callback
 */
void timer_set_callback(timer_device_t *timer, timer_callback_t cb, void *arg) {
    if (!timer) return;
    timer->callback = cb;
    timer->callback_arg = arg;
}

/*
 * Start the timer
 */
void timer_start(timer_device_t *timer, uint64_t interval_us) {
    if (!timer || !timer->initialized) return;

    if (timer->type == TIMER_HPET && hpet_base) {
        hpet_set_timer(0, interval_us * hpet_frequency / 1000000, 1);
    }
}

/*
 * Stop the timer
 */
void timer_stop(timer_device_t *timer) {
    if (!timer || !timer->initialized) return;
    /* PIT cannot be stopped easily */
}

/*
 * Get timer ticks
 */
uint64_t timer_get_ticks(timer_device_t *timer) {
    if (!timer) return 0;
    return timer->ticks;
}

/*
 * Get uptime in milliseconds
 */
uint64_t timer_get_uptime_ms(timer_device_t *timer) {
    if (!timer) return 0;
    return timer->uptime_ms;
}

/*
 * Delay for microseconds (busy-wait)
 */
void timer_delay_us(timer_device_t *timer, uint64_t us) {
    if (!timer) return;

    if (timer->type == TIMER_HPET && hpet_base) {
        uint64_t start = hpet_read_counter();
        uint64_t ticks = us * hpet_frequency / 1000000;
        while (hpet_read_counter() - start < ticks) {
            __asm__ volatile("pause");
        }
    } else {
        /* PIT-based delay: approximate using I/O port reads */
        for (uint64_t i = 0; i < us * 4; i++) {
            __asm__ volatile("pause");
        }
    }
}

/*
 * Delay for milliseconds
 */
void timer_delay_ms(timer_device_t *timer, uint64_t ms) {
    timer_delay_us(timer, ms * 1000);
}

/*
 * Get system uptime (global)
 */
uint64_t get_uptime_ms(void) {
    return timer_get_uptime_ms(&g_system_timer);
}

/*
 * Microsecond delay (global)
 */
void udelay(uint64_t us) {
    timer_delay_us(&g_system_timer, us);
}

/*
 * Millisecond delay (global)
 */
void mdelay(uint64_t ms) {
    timer_delay_ms(&g_system_timer, ms);
}

/*
 * Timer interrupt handler (called from IRQ0)
 */
void timer_interrupt_handler(void) {
    g_system_timer.ticks++;

    /* Update uptime (assuming 100 Hz timer = 10ms per tick) */
    if (g_system_timer.ticks % 100 == 0) {
        g_system_timer.uptime_ms += 1000;
    }

    /* Call registered callback */
    if (g_system_timer.callback) {
        g_system_timer.callback(g_system_timer.callback_arg);
    }
}