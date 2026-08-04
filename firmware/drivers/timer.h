/*
 * AinosOS - drivers/timer.h
 * Timer driver declarations (PIT, HPET, APIC timer)
 */

#ifndef AINOS_DRIVERS_TIMER_H
#define AINOS_DRIVERS_TIMER_H

#include <types.h>

/* PIT (Programmable Interval Timer) registers */
#define PIT_CH0         0x40
#define PIT_CH1         0x41
#define PIT_CH2         0x42
#define PIT_CMD         0x43

/* PIT command bits */
#define PIT_SEL_CH0     0x00
#define PIT_SEL_CH1     0x40
#define PIT_SEL_CH2     0x80
#define PIT_READBACK    0xC0
#define PIT_ACCESS_LH    0x30  /* Lobyte then hibyte */
#define PIT_MODE0       0x00  /* Interrupt on terminal count */
#define PIT_MODE2       0x04  /* Rate generator */
#define PIT_MODE3       0x06  /* Square wave generator */
#define PIT_BCD         0x01  /* BCD mode */

/* PIT frequency */
#define PIT_BASE_FREQ   1193182  /* 1.193182 MHz */

/* HPET registers */
#define HPET_GCAP_ID    0x000
#define HPET_GEN_CONF   0x010
#define HPET_GEN_STAT   0x020
#define HPET_MAIN_CNT   0x0F0
#define HPET_TIMER0_CONF 0x100
#define HPET_TIMER0_COMP 0x108
#define HPET_TIMER0_FSB  0x110

/* HPET timer configuration */
#define HPET_TN_ENABLE      (1ULL << 0)
#define HPET_TN_PERIODIC    (1ULL << 1)
#define HPET_TN_SET_ACCUM   (1ULL << 1)
#define HPET_TN_32BIT       (1ULL << 8)
#define HPET_TN_FSB_ENABLE  (1ULL << 14)
#define HPET_TN_FSB_INT     (1ULL << 15)
#define HPET_TN_INT_ROUTE   (1ULL << 9)
#define HPET_TN_TYPE_CNF    (1ULL << 3)

/* Timer device types */
typedef enum {
    TIMER_PIT,
    TIMER_HPET,
    TIMER_APIC,
    TIMER_LAPIC
} timer_type_t;

/* Timer callback */
typedef void (*timer_callback_t)(void *arg);

/* Timer device structure */
typedef struct {
    timer_type_t type;
    int initialized;
    uint64_t frequency;
    uint64_t ticks;
    volatile uint64_t uptime_ms;
    timer_callback_t callback;
    void *callback_arg;
} timer_device_t;

/* Timer functions */
int  timer_init(timer_device_t *timer);
void timer_set_callback(timer_device_t *timer, timer_callback_t cb, void *arg);
void timer_start(timer_device_t *timer, uint64_t interval_us);
void timer_stop(timer_device_t *timer);
uint64_t timer_get_ticks(timer_device_t *timer);
uint64_t timer_get_uptime_ms(timer_device_t *timer);
void timer_delay_us(timer_device_t *timer, uint64_t us);
void timer_delay_ms(timer_device_t *timer, uint64_t ms);

/* PIT-specific functions */
void pit_init(uint32_t frequency);
void pit_set_frequency(uint32_t frequency);
void pit_set_one_shot(uint32_t count);
uint32_t pit_read_count(void);

/* HPET-specific functions */
int  hpet_init(void);
void hpet_start(void);
void hpet_stop(void);
uint64_t hpet_read_counter(void);
void hpet_set_timer(uint32_t timer_num, uint64_t interval, int periodic);
uint64_t hpet_get_frequency(void);

/* Timekeeping */
uint64_t get_uptime_ms(void);
void udelay(uint64_t us);
void mdelay(uint64_t ms);

/* Global timer device */
extern timer_device_t g_system_timer;

#endif /* AINOS_DRIVERS_TIMER_H */