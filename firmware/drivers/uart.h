/*
 * AinosOS - drivers/uart.h
 * UART serial port driver declarations
 */

#ifndef AINOS_DRIVERS_UART_H
#define AINOS_DRIVERS_UART_H

#include <types.h>

/* UART port definitions */
#define UART_COM1  0x3F8
#define UART_COM2  0x2F8
#define UART_COM3  0x3E8
#define UART_COM4  0x2E8

/* UART register offsets */
#define UART_RX    0   /* Receive buffer (read) */
#define UART_TX    0   /* Transmit buffer (write) */
#define UART_IER   1   /* Interrupt Enable Register */
#define UART_IIR   2   /* Interrupt Identification Register */
#define UART_FCR   2   /* FIFO Control Register */
#define UART_LCR   3   /* Line Control Register */
#define UART_MCR   4   /* Modem Control Register */
#define UART_LSR   5   /* Line Status Register */
#define UART_MSR   6   /* Modem Status Register */
#define UART_SCR   7   /* Scratch Register */

/* UART LCR bits */
#define UART_LCR_5BIT   0x00
#define UART_LCR_6BIT   0x01
#define UART_LCR_7BIT   0x02
#define UART_LCR_8BIT   0x03
#define UART_LCR_1STOP  0x00
#define UART_LCR_2STOP  0x04
#define UART_LCR_NOPAR  0x00
#define UART_LCR_PAR    0x08
#define UART_LCR_EVEN   0x10
#define UART_LCR_STICK  0x20
#define UART_LCR_BREAK  0x40
#define UART_LCR_DLAB   0x80

/* UART LSR bits */
#define UART_LSR_DR     0x01  /* Data Ready */
#define UART_LSR_OE     0x02  /* Overrun Error */
#define UART_LSR_PE     0x04  /* Parity Error */
#define UART_LSR_FE     0x08  /* Framing Error */
#define UART_LSR_BI     0x10  /* Break Interrupt */
#define UART_LSR_THRE   0x20  /* Transmitter Holding Register Empty */
#define UART_LSR_TEMT   0x40  /* Transmitter Empty */
#define UART_LSR_ERR    0x80  /* Error in FIFO */

/* UART IRQ numbers */
#define UART_IRQ_COM1   4
#define UART_IRQ_COM2   3
#define UART_IRQ_COM3   4
#define UART_IRQ_COM4   3

/* UART baud rates */
#define UART_BAUD_115200   1
#define UART_BAUD_57600    2
#define UART_BAUD_38400    3
#define UART_BAUD_19200    6
#define UART_BAUD_9600     12
#define UART_BAUD_4800     24
#define UART_BAUD_2400     48
#define UART_BAUD_1200     96

/* UART device structure */
typedef struct {
    uint16_t port;
    int irq;
    int initialized;
    int baud_rate;
    uint8_t config;
    volatile int tx_busy;
    char rx_buffer[256];
    int rx_head;
    int rx_tail;
} uart_device_t;

/* UART functions */
int  uart_init(uart_device_t *dev, uint16_t port);
void uart_set_baud(uart_device_t *dev, int baud_divisor);
void uart_set_config(uart_device_t *dev, uint8_t config);
void uart_putchar(uart_device_t *dev, char c);
int  uart_getchar(uart_device_t *dev);
void uart_puts(uart_device_t *dev, const char *s);
int  uart_read_ready(uart_device_t *dev);
void uart_flush(uart_device_t *dev);
void uart_enable_interrupts(uart_device_t *dev);
void uart_disable_interrupts(uart_device_t *dev);
void uart_irq_handler(uart_device_t *dev);

/* Global UART devices */
extern uart_device_t uart_com1;

#endif /* AINOS_DRIVERS_UART_H */