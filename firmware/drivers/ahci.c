/*
 * AinosOS - drivers/ahci.c
 * AHCI driver implementation
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <drivers/pci.h>
#include <drivers/ahci.h>

/* Global AHCI device */
ahci_device_t g_ahci_dev = { 0 };

/* AHCI memory for port 0 */
static struct ahci_hba_mem g_ahci_mem ALIGNED(4096);

/*
 * Find AHCI controller on PCI bus
 */
int ahci_find_controller(void) {
    for (int i = 0; i < pci_get_device_count(); i++) {
        pci_device_t *pci_dev = pci_get_device(i);
        if (pci_dev && pci_dev->class_code == 0x01 && pci_dev->subclass == 0x06) {
            boot_printf("  AHCI controller found at %02X:%02X.%X\n",
                        pci_dev->bus, pci_dev->device, pci_dev->function);

            /* Read BAR5 (AHCI base) */
            uint32_t bar5 = pci_dev->bars[5];
            uint64_t mmio_base;

            if (bar5 & 4) {
                uint32_t bar4 = pci_dev->bars[4];
                mmio_base = (uint64_t)(bar5 & ~0xF) | ((uint64_t)bar4 << 32);
            } else {
                mmio_base = bar5 & ~0xF;
            }

            /* Enable bus mastering and MMIO */
            pci_enable_bus_mastering(pci_dev->bus, pci_dev->device, pci_dev->function);
            pci_enable_mmio(pci_dev->bus, pci_dev->device, pci_dev->function);

            return ahci_init(&g_ahci_dev, mmio_base);
        }
    }
    return -1;
}

/*
 * Initialize AHCI controller
 */
int ahci_init(ahci_device_t *dev, uint64_t mmio_base) {
    boot_printf(BOOT_LOG_INIT "Initializing AHCI at 0x%016llX...\n", mmio_base);

    dev->mmio_base = mmio_base;
    dev->initialized = 0;

    volatile uint32_t *hba = (volatile uint32_t*)(uint64_t)mmio_base;

    /* Enable AHCI mode */
    hba[AHCI_GHC / 4] |= AHCI_GHC_AE;

    /* Read capabilities */
    uint32_t cap = hba[AHCI_CAP / 4];
    uint32_t vs = hba[AHCI_VS / 4];
    uint32_t pi = hba[AHCI_PI / 4];

    dev->port_count = (cap & 0x1F) + 1;

    boot_printf("  Version: %u.%u, Ports: %u, PI: 0x%08X\n",
                (vs >> 8) & 0xFF, vs & 0xFF, dev->port_count, pi);

    /* Initialize each port */
    for (int i = 0; i < 32 && i < dev->port_count; i++) {
        if (pi & (1 << i)) {
            dev->ports[i].port_num = i;
            dev->ports[i].port_base = hba + (0x100 + i * 0x80) / 4;
            dev->ports[i].present = 0;
            dev->ports[i].mem = &g_ahci_mem;

            ahci_port_init(dev, i);
        }
    }

    dev->initialized = 1;
    boot_printf(BOOT_LOG_OK "AHCI initialized\n");

    return 0;
}

/*
 * Initialize an AHCI port
 */
int ahci_port_init(ahci_device_t *dev, int port_num) {
    if (port_num < 0 || port_num >= 32) return -1;

    ahci_port_t *port = &dev->ports[port_num];
    volatile uint32_t *base = port->port_base;

    /* Stop the port */
    ahci_port_stop(port);

    /* Check if device is present */
    uint32_t ssts = base[AHCI_PORT_SSTS / 4];
    uint8_t det = ssts & 0x0F;
    uint8_t ipm = (ssts >> 8) & 0x0F;

    if (det != 0x03 || ipm != 0x01) {
        port->present = 0;
        return -1;
    }

    port->present = 1;
    boot_printf("  Port %d: Device present\n", port_num);

    /* Set up command list base */
    base[AHCI_PORT_LBASE / 4] = (uint32_t)(uint64_t)port->mem;
    base[AHCI_PORT_HBASE / 4] = (uint32_t)((uint64_t)port->mem >> 32);

    /* Set up FIS base */
    base[AHCI_PORT_FB / 4] = (uint32_t)((uint64_t)port->mem + 0x400);
    base[AHCI_PORT_FB / 4 + 1] = (uint32_t)(((uint64_t)port->mem + 0x400) >> 32);

    /* Clear interrupt status */
    base[AHCI_PORT_IS / 4] = 0xFFFFFFFF;

    /* Enable interrupts */
    uint32_t ie = AHCI_IS_DHRS | AHCI_IS_PSS | AHCI_IS_TFES |
                  AHCI_IS_HBFS | AHCI_IS_HBDS | AHCI_IS_IFS |
                  AHCI_IS_INFS | AHCI_IS_OFS | AHCI_IS_IPMS |
                  AHCI_IS_PRCS | AHCI_IS_SDBS | AHCI_IS_DSS;
    base[AHCI_PORT_IE / 4] = ie;

    /* Start the port */
    ahci_port_start(port);

    /* Read signature */
    uint32_t sig = base[AHCI_PORT_SIG / 4];
    port->atapi = (sig == 0xEB140101) ? 1 : 0;

    /* Identify device */
    if (ahci_identify(port) != 0) {
        boot_printf(BOOT_LOG_WARN "  Port %d: Identify failed\n", port_num);
        return -1;
    }

    return 0;
}

/*
 * Stop an AHCI port
 */
void ahci_port_stop(ahci_port_t *port) {
    volatile uint32_t *base = port->port_base;

    /* Clear ST (start) bit */
    base[AHCI_PORT_CMD / 4] &= ~AHCI_CMD_ST;

    /* Wait for FR (FIS receive running) and CR (command list running) to clear */
    for (int timeout = 0; timeout < 100000; timeout++) {
        if (!(base[AHCI_PORT_CMD / 4] & (AHCI_CMD_FR | AHCI_CMD_CR))) {
            break;
        }
        udelay(1);
    }

    /* Clear FRE (FIS receive enable) */
    base[AHCI_PORT_CMD / 4] &= ~AHCI_CMD_FRE;
}

/*
 * Start an AHCI port
 */
void ahci_port_start(ahci_port_t *port) {
    volatile uint32_t *base = port->port_base;

    /* Set FRE (FIS receive enable) */
    base[AHCI_PORT_CMD / 4] |= AHCI_CMD_FRE;

    /* Set SUD (spin-up device) */
    base[AHCI_PORT_CMD / 4] |= AHCI_CMD_SUD;

    /* Set POD (power-on device) */
    base[AHCI_PORT_CMD / 4] |= AHCI_CMD_POD;

    /* Set ST (start) */
    base[AHCI_PORT_CMD / 4] |= AHCI_CMD_ST;
}

/*
 * Send an ATA command via AHCI
 */
static int ahci_send_cmd(ahci_port_t *port, uint8_t *cfis, int write,
                          uint64_t buffer, uint32_t sector_count) {
    volatile uint32_t *base = port->port_base;
    uint32_t slot = 0;

    /* Find a free command slot */
    uint32_t ci = base[AHCI_PORT_CI / 4];
    uint32_t sact = base[AHCI_PORT_SACT / 4];
    uint32_t used = ci | sact;

    for (int i = 0; i < 32; i++) {
        if (!(used & (1 << i))) {
            slot = i;
            break;
        }
    }

    /* Set up command header */
    struct ahci_cmd_header *cmd_header = (struct ahci_cmd_header*)port->mem;
    cmd_header[slot].cfis_len = sizeof(uint64_t) * 5 / 4;  /* 5 dwords */
    cmd_header[slot].write = write ? 1 : 0;
    cmd_header[slot].prdtl = 0;
    cmd_header[slot].prdbc = 0;

    /* Copy CFIS (Command FIS) */
    uint8_t *acmd = (uint8_t*)(port->mem + 0x40 + slot * 0x100);
    memcpy(acmd, cfis, 64);

    /* Set up PRDT if needed */
    if (buffer && sector_count > 0) {
        uint32_t bytes = sector_count * 512;
        uint32_t prdt_count = (bytes + 4095) / 4096;
        cmd_header[slot].prdtl = prdt_count;

        struct ahci_prdt_entry *prdt = (struct ahci_prdt_entry*)(port->mem + 0x40 + slot * 0x100 + 0x60);
        for (uint32_t i = 0; i < prdt_count; i++) {
            prdt[i].dba = buffer + i * 4096;
            prdt[i].dbc = (i == prdt_count - 1) ?
                (bytes - i * 4096 - 1) : 4095;
        }
    }

    /* Ensure updates are visible */
    __sync_synchronize();

    /* Clear interrupt status */
    base[AHCI_PORT_IS / 4] = 0xFFFFFFFF;

    /* Issue command */
    base[AHCI_PORT_CI / 4] = (1 << slot);

    /* Wait for completion */
    for (uint64_t timeout = 0; timeout < 10000000; timeout++) {
        if (!(base[AHCI_PORT_CI / 4] & (1 << slot))) {
            /* Check for errors */
            uint32_t is = base[AHCI_PORT_IS / 4];
            if (is & AHCI_IS_TFES) {
                return -1;
            }
            return 0;
        }
        udelay(1);
    }

    return -1;  /* Timeout */
}

/*
 * Identify device
 */
int ahci_identify(ahci_port_t *port) {
    uint8_t cfis[64] = { 0 };
    uint16_t identify_data[256];
    uint64_t phys_addr = (uint64_t)identify_data;

    /* Build FIS (Host to Device) */
    cfis[0] = SATA_FIS_TYPE_H2D;
    cfis[1] = 0x80;  /* Command bit */
    cfis[2] = ATA_CMD_IDENTIFY;
    cfis[3] = 0;
    cfis[4] = 0;
    cfis[5] = 0;
    cfis[6] = 0;
    cfis[7] = 0;
    cfis[8] = 0;
    cfis[9] = 0;
    cfis[10] = 0;
    cfis[11] = 0;
    cfis[12] = 0;
    cfis[13] = 0;
    cfis[14] = 0;
    cfis[15] = 0;

    int ret = ahci_send_cmd(port, cfis, 0, phys_addr, 1);

    if (ret == 0) {
        /* Parse identify data */
        uint64_t lba_sectors = *(uint64_t*)&identify_data[100];
        port->capacity = lba_sectors * 512;
        port->sector_size = 512;
        port->max_lba = (uint32_t)(lba_sectors & 0xFFFFFFFF);

        /* Get model string */
        char model[41] = { 0 };
        for (int i = 0; i < 40; i += 2) {
            model[i] = identify_data[27 + i / 2] >> 8;
            model[i + 1] = identify_data[27 + i / 2] & 0xFF;
        }

        boot_printf("    Model: %s, Capacity: %llu MB\n",
                    model, port->capacity / (1024 * 1024));
    }

    return ret;
}

/*
 * Read from AHCI port
 */
int ahci_read(ahci_port_t *port, uint64_t lba, uint32_t count, void *buffer) {
    if (!port || !port->present || !buffer) return -1;

    uint8_t cfis[64] = { 0 };

    cfis[0] = SATA_FIS_TYPE_H2D;
    cfis[1] = 0x80;

    if (lba < 0x10000000 && count <= 256) {
        /* 28-bit LBA */
        cfis[2] = ATA_CMD_READ_DMA;
        cfis[4] = (uint8_t)(lba & 0xFF);
        cfis[5] = (uint8_t)((lba >> 8) & 0xFF);
        cfis[6] = (uint8_t)((lba >> 16) & 0xFF);
        cfis[7] = 0x40 | ((lba >> 24) & 0x0F);
        cfis[12] = (uint8_t)(count & 0xFF);
        cfis[13] = count > 255 ? 0 : (uint8_t)(count >> 8);
    } else {
        /* 48-bit LBA */
        cfis[2] = ATA_CMD_READ_DMA_EXT;
        cfis[4] = (uint8_t)(lba & 0xFF);
        cfis[5] = (uint8_t)((lba >> 8) & 0xFF);
        cfis[6] = (uint8_t)((lba >> 16) & 0xFF);
        cfis[7] = 0x40;
        cfis[8] = (uint8_t)((lba >> 24) & 0xFF);
        cfis[9] = (uint8_t)((lba >> 32) & 0xFF);
        cfis[10] = (uint8_t)((lba >> 40) & 0xFF);
        cfis[12] = (uint8_t)(count & 0xFF);
        cfis[13] = (uint8_t)((count >> 8) & 0xFF);
    }

    return ahci_send_cmd(port, cfis, 0, (uint64_t)buffer, count);
}

/*
 * Write to AHCI port
 */
int ahci_write(ahci_port_t *port, uint64_t lba, uint32_t count, const void *buffer) {
    if (!port || !port->present || !buffer) return -1;

    uint8_t cfis[64] = { 0 };

    cfis[0] = SATA_FIS_TYPE_H2D;
    cfis[1] = 0x80;

    if (lba < 0x10000000 && count <= 256) {
        cfis[2] = ATA_CMD_WRITE_DMA;
        cfis[4] = (uint8_t)(lba & 0xFF);
        cfis[5] = (uint8_t)((lba >> 8) & 0xFF);
        cfis[6] = (uint8_t)((lba >> 16) & 0xFF);
        cfis[7] = 0x40 | ((lba >> 24) & 0x0F);
        cfis[12] = (uint8_t)(count & 0xFF);
        cfis[13] = count > 255 ? 0 : (uint8_t)(count >> 8);
    } else {
        cfis[2] = ATA_CMD_WRITE_DMA_EXT;
        cfis[4] = (uint8_t)(lba & 0xFF);
        cfis[5] = (uint8_t)((lba >> 8) & 0xFF);
        cfis[6] = (uint8_t)((lba >> 16) & 0xFF);
        cfis[7] = 0x40;
        cfis[8] = (uint8_t)((lba >> 24) & 0xFF);
        cfis[9] = (uint8_t)((lba >> 32) & 0xFF);
        cfis[10] = (uint8_t)((lba >> 40) & 0xFF);
        cfis[12] = (uint8_t)(count & 0xFF);
        cfis[13] = (uint8_t)((count >> 8) & 0xFF);
    }

    return ahci_send_cmd(port, cfis, 1, (uint64_t)buffer, count);
}

/*
 * Flush AHCI port
 */
int ahci_flush(ahci_port_t *port) {
    uint8_t cfis[64] = { 0 };

    cfis[0] = SATA_FIS_TYPE_H2D;
    cfis[1] = 0x80;
    cfis[2] = ATA_CMD_FLUSH_CACHE_EXT;

    return ahci_send_cmd(port, cfis, 0, 0, 0);
}