/*
 * AinosOS - drivers/uart.c
 * UART serial port driver implementation
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/io.h>
#include <drivers/uart.h>

/* Default UART device for COM1 */
uart_device_t uart_com1 = { 0 };

/*
 * Initialize a UART device
 */
int uart_init(uart_device_t *dev, uint16_t port) {
    if (!dev) return -1;

    dev->port = port;
    dev->initialized = 0;
    dev->rx_head = 0;
    dev->rx_tail = 0;
    dev->tx_busy = 0;

    /* Set appropriate IRQ based on port */
    switch (port) {
        case UART_COM1: dev->irq = UART_IRQ_COM1; break;
        case UART_COM2: dev->irq = UART_IRQ_COM2; break;
        case UART_COM3: dev->irq = UART_IRQ_COM3; break;
        case UART_COM4: dev->irq = UART_IRQ_COM4; break;
        default: return -1;
    }

    /* Disable interrupts */
    io_outb(port + UART_IER, 0x00);

    /* Set DLAB to access baud rate divisor */
    io_outb(port + UART_LCR, UART_LCR_DLAB);

    /* Set baud rate to 115200 by default */
    io_outb(port + UART_TX, 0x01);   /* Divisor low */
    io_outb(port + UART_IER, 0x00);  /* Divisor high */

    /* Set line: 8N1 */
    io_outb(port + UART_LCR, UART_LCR_8BIT | UART_LCR_1STOP | UART_LCR_NOPAR);

    /* Enable FIFO, clear, 14-byte threshold */
    io_outb(port + UART_FCR, 0xC7);

    /* Enable IRQ, RTS/DSR set */
    io_outb(port + UART_MCR, 0x0B);

    /* Clear any pending interrupts */
    io_inb(port + UART_RX);

    /* Perform loopback test to verify port is present */
    io_outb(port + UART_MCR, 0x1E);  /* Set loopback mode */
    io_outb(port + UART_TX, 0xAE);   /* Send test byte */
    if (io_inb(port + UART_RX) != 0xAE) {
        /* No UART at this port */
        io_outb(port + UART_MCR, 0x0E);
        return -1;
    }

    /* Restore normal operation */
    io_outb(port + UART_MCR, 0x0F);

    dev->initialized = 1;
    return 0;
}

/*
 * Change the baud rate of the UART
 */
void uart_set_baud(uart_device_t *dev, int baud_divisor) {
    if (!dev || !dev->initialized) return;

    uint16_t port = dev->port;

    /* Set DLAB */
    uint8_t lcr = io_inb(port + UART_LCR);
    io_outb(port + UART_LCR, lcr | UART_LCR_DLAB);

    /* Set divisor */
    io_outb(port + UART_TX, baud_divisor & 0xFF);
    io_outb(port + UART_IER, (baud_divisor >> 8) & 0xFF);

    /* Restore LCR */
    io_outb(port + UART_LCR, lcr);

    dev->baud_rate = baud_divisor;
}

/*
 * Set line configuration
 */
void uart_set_config(uart_device_t *dev, uint8_t config) {
    if (!dev || !dev->initialized) return;

    uint16_t port = dev->port;
    uint8_t lcr = io_inb(port + UART_LCR);

    /* Clear data bits, stop bits, parity */
    lcr &= 0x3F;
    lcr |= config & 0x3F;

    io_outb(port + UART_LCR, lcr);
    dev->config = config;
}

/*
 * Write a character to the UART
 */
void uart_putchar(uart_device_t *dev, char c) {
    if (!dev || !dev->initialized) return;

    uint16_t port = dev->port;

    /* Wait for transmitter holding register to be empty */
    for (int timeout = 0; timeout < 100000; timeout++) {
        if (io_inb(port + UART_LSR) & UART_LSR_THRE) {
            break;
        }
    }

    io_outb(port + UART_TX, (uint8_t)c);

    /* Handle LF -> CRLF conversion */
    if (c == '\n') {
        for (int timeout = 0; timeout < 100000; timeout++) {
            if (io_inb(port + UART_LSR) & UART_LSR_THRE) {
                break;
            }
        }
        io_outb(port + UART_TX, '\r');
    }
}

/*
 * Read a character from the UART (blocking)
 */
int uart_getchar(uart_device_t *dev) {
    if (!dev || !dev->initialized) return -1;

    uint16_t port = dev->port;

    /* Wait for data to be available */
    for (int timeout = 0; timeout < 100000; timeout++) {
        if (io_inb(port + UART_LSR) & UART_LSR_DR) {
            return io_inb(port + UART_RX);
        }
    }

    return -1;  /* Timeout */
}

/*
 * Write a string to the UART
 */
void uart_puts(uart_device_t *dev, const char *s) {
    if (!dev || !s) return;

    while (*s) {
        uart_putchar(dev, *s++);
    }
    uart_putchar(dev, '\n');
}

/*
 * Check if data is available to read
 */
int uart_read_ready(uart_device_t *dev) {
    if (!dev || !dev->initialized) return 0;

    uint16_t port = dev->port;
    return (io_inb(port + UART_LSR) & UART_LSR_DR) ? 1 : 0;
}

/*
 * Flush the UART (wait for all data to be transmitted)
 */
void uart_flush(uart_device_t *dev) {
    if (!dev || !dev->initialized) return;

    uint16_t port = dev->port;

    for (int timeout = 0; timeout < 100000; timeout++) {
        if (io_inb(port + UART_LSR) & UART_LSR_TEMT) {
            break;
        }
    }
}

/*
 * Enable UART interrupts
 */
void uart_enable_interrupts(uart_device_t *dev) {
    if (!dev || !dev->initialized) return;

    /* Enable received data available interrupt */
    io_outb(dev->port + UART_IER, 0x01);
}

/*
 * Disable UART interrupts
 */
void uart_disable_interrupts(uart_device_t *dev) {
    if (!dev || !dev->initialized) return;

    io_outb(dev->port + UART_IER, 0x00);
}

/*
 * UART interrupt handler
 */
void uart_irq_handler(uart_device_t *dev) {
    if (!dev || !dev->initialized) return;

    uint16_t port = dev->port;

    /* Read interrupt identification */
    uint8_t iir = io_inb(port + UART_IIR);

    if (iir & 1) {
        /* No interrupt pending (spurious) */
        return;
    }

    /* Check for received data available */
    if ((iir & 0x0E) == 0x04) {
        /* Read all available data */
        while (io_inb(port + UART_LSR) & UART_LSR_DR) {
            char c = io_inb(port + UART_RX);
            int next = (dev->rx_head + 1) % sizeof(dev->rx_buffer);
            if (next != dev->rx_tail) {
                dev->rx_buffer[dev->rx_head] = c;
                dev->rx_head = next;
            }
        }
    }

    /* Check for transmitter holding register empty */
    if ((iir & 0x0E) == 0x02) {
        dev->tx_busy = 0;
    }
}

/*
 * Non-blocking read from UART buffer
 */
int uart_read_nonblock(uart_device_t *dev) {
    if (!dev || !dev->initialized) return -1;
    if (dev->rx_head == dev->rx_tail) return -1;

    char c = dev->rx_buffer[dev->rx_tail];
    dev->rx_tail = (dev->rx_tail + 1) % sizeof(dev->rx_buffer);
    return c;
}

/*
 * Initialize COM1 as the default system console
 */
void uart_init_console(void) {
    if (uart_init(&uart_com1, UART_COM1) == 0) {
        uart_puts(&uart_com1, "AinosOS UART console initialized");
    }
}