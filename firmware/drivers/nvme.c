/*
 * AinosOS - drivers/nvme.c
 * NVMe driver implementation
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <drivers/pci.h>
#include <drivers/nvme.h>

/* Global NVMe device */
nvme_device_t g_nvme_dev = { 0 };

/* Memory for admin queues */
static struct nvme_command g_admin_sq[64] ALIGNED(PAGE_SIZE);
static struct nvme_completion g_admin_cq[64] ALIGNED(PAGE_SIZE);

/* Memory for IO queues */
static struct nvme_command g_io_sq[256] ALIGNED(PAGE_SIZE);
static struct nvme_completion g_io_cq[256] ALIGNED(PAGE_SIZE);

/*
 * Read an NVMe MMIO register
 */
static inline uint32_t nvme_read32(nvme_device_t *dev, uint32_t offset) {
    return *(volatile uint32_t*)(uint64_t)(dev->mmio_base + offset);
}

static inline uint64_t nvme_read64(nvme_device_t *dev, uint32_t offset) {
    return *(volatile uint64_t*)(uint64_t)(dev->mmio_base + offset);
}

/*
 * Write an NVMe MMIO register
 */
static inline void nvme_write32(nvme_device_t *dev, uint32_t offset, uint32_t val) {
    *(volatile uint32_t*)(uint64_t)(dev->mmio_base + offset) = val;
}

static inline void nvme_write64(nvme_device_t *dev, uint32_t offset, uint64_t val) {
    *(volatile uint64_t*)(uint64_t)(dev->mmio_base + offset) = val;
}

/*
 * Wait for a controller status bit
 */
static int nvme_wait_csts(nvme_device_t *dev, uint32_t mask, uint32_t val, uint64_t timeout_us) {
    for (uint64_t i = 0; i < timeout_us; i++) {
        if ((nvme_read32(dev, NVME_REG_CSTS) & mask) == val) {
            return 0;
        }
        udelay(1);
    }
    return -1;
}

/*
 * Initialize an NVMe controller
 */
int nvme_init(nvme_device_t *dev, uint8_t bus, uint8_t dev_num, uint8_t func) {
    if (!dev) return -1;

    boot_printf(BOOT_LOG_INIT "Initializing NVMe controller at %02X:%02X.%X...\n",
                bus, dev_num, func);

    dev->bus = bus;
    dev->dev = dev_num;
    dev->func = func;
    dev->initialized = 0;

    /* Read BAR0 (should be MMIO) */
    uint32_t bar0 = pci_read_bar(bus, dev_num, func, 0);
    uint64_t mmio_base;

    if (bar0 & 1) {
        /* I/O BAR - not expected for NVMe */
        boot_printf(BOOT_LOG_FAIL "NVMe BAR0 is I/O space\n");
        return -1;
    }

    if (bar0 & 4) {
        /* 64-bit BAR */
        uint32_t bar1 = pci_read_bar(bus, dev_num, func, 1);
        mmio_base = (uint64_t)bar1 << 32 | (bar0 & ~0xF);
    } else {
        mmio_base = bar0 & ~0xF;
    }

    dev->mmio_base = mmio_base;
    dev->vendor_id = pci_read_vendor(bus, dev_num, func);
    dev->device_id = pci_read_device_id(bus, dev_num, func);

    boot_printf("  MMIO base: 0x%016llX\n", mmio_base);

    /* Enable PCI bus mastering and MMIO */
    pci_enable_bus_mastering(bus, dev_num, func);
    pci_enable_mmio(bus, dev_num, func);

    /* Read capabilities */
    uint64_t cap = nvme_read64(dev, NVME_REG_CAP);
    uint32_t vs = nvme_read32(dev, NVME_REG_VS);

    uint32_t mps_min = 1 << (12 + ((cap >> 48) & 0xF));  /* CAP.MPSMIN */
    uint32_t mps_max = 1 << (12 + ((cap >> 52) & 0xF));  /* CAP.MPSMAX */
    uint32_t doorbell_stride = (cap >> 32) & 0xF;  /* DSTRD */
    uint32_t timeout = ((cap >> 24) & 0xFF) * 500;  /* CAP.TO in 500ms units */

    dev->page_size = mps_min;
    dev->max_transfer = 1 << (12 + ((cap >> 0) & 0xF));  /* MQES + 1 */

    boot_printf("  Version: %u.%u.%u\n", (vs >> 16) & 0xFF, (vs >> 8) & 0xFF, vs & 0xFF);
    boot_printf("  Page size: %u, Max transfer: %u\n", dev->page_size, dev->max_transfer);

    /* Disable the controller */
    nvme_write32(dev, NVME_REG_CC, 0);

    /* Wait for controller to become not ready */
    if (nvme_wait_csts(dev, NVME_CSTS_RDY, 0, timeout * 1000) != 0) {
        boot_printf(BOOT_LOG_FAIL "NVMe controller failed to become not ready\n");
        return -1;
    }

    /* Set up admin queues */
    dev->admin_sq = g_admin_sq;
    dev->admin_cq = g_admin_cq;
    dev->admin_sq_tail = 0;
    dev->admin_cq_head = 0;
    dev->admin_sq_doorbell = doorbell_stride * 4;
    dev->admin_cq_doorbell = 0x1000 + doorbell_stride * 4;

    /* Set admin queue attributes */
    uint32_t aqa = 63;  /* Queue size = 64 entries */
    nvme_write32(dev, NVME_REG_AQA, aqa | (aqa << 16));

    /* Set admin submission queue base address */
    nvme_write64(dev, NVME_REG_ASQ, (uint64_t)dev->admin_sq);
    nvme_write64(dev, NVME_REG_ACQ, (uint64_t)dev->admin_cq);

    /* Configure controller */
    uint32_t cc = (0 << 0) |           /* Enable = 0 (don't start yet) */
                  (0 << 4) |           /* CSS NVM */
                  (0 << 7) |           /* MPS = 0 (4KB pages) */
                  (0 << 11) |          /* CSS = NVM */
                  (6 << 16) |           /* IOSQES = 64 bytes */
                  (4 << 20);            /* IOCQES = 16 bytes */
    nvme_write32(dev, NVME_REG_CC, cc);

    /* Enable the controller */
    nvme_write32(dev, NVME_REG_CC, cc | NVME_CC_ENABLE);

    /* Wait for controller to become ready */
    if (nvme_wait_csts(dev, NVME_CSTS_RDY, NVME_CSTS_RDY, timeout * 1000) != 0) {
        boot_printf(BOOT_LOG_FAIL "NVMe controller failed to become ready\n");
        return -1;
    }

    boot_printf(BOOT_LOG_OK "NVMe controller enabled\n");

    /* Identify controller */
    if (nvme_identify_ctrl(dev) != 0) {
        boot_printf(BOOT_LOG_FAIL "NVMe identify controller failed\n");
        return -1;
    }

    /* Identify namespace 1 */
    if (nvme_identify_ns(dev, 1) != 0) {
        boot_printf(BOOT_LOG_FAIL "NVMe identify namespace failed\n");
        return -1;
    }

    /* Create IO queues */
    if (nvme_create_io_queues(dev, 256) != 0) {
        boot_printf(BOOT_LOG_WARN "NVMe IO queue creation failed, using admin queue only\n");
    }

    dev->initialized = 1;
    boot_printf(BOOT_LOG_OK "NVMe initialized: %s\n", dev->ctrl_data.mn);
    boot_printf("  Capacity: %llu MB (%llu sectors of %u bytes)\n",
                dev->capacity / (1024 * 1024),
                dev->ns_data.nsze, dev->lba_size);

    return 0;
}

/*
 * Submit an admin command and wait for completion
 */
int nvme_admin_command(nvme_device_t *dev, struct nvme_command *cmd,
                        struct nvme_completion *comp) {
    if (!dev || !cmd) return -1;

    /* Set command ID */
    static uint16_t cmd_id = 0;
    cmd->dword0.command_id = cmd_id++;

    /* Copy command to submission queue */
    uint32_t tail = dev->admin_sq_tail;
    dev->admin_sq[tail] = *cmd;

    /* Ensure command is visible before ringing doorbell */
    __sync_synchronize();

    /* Ring doorbell */
    nvme_write32(dev, dev->admin_sq_doorbell, tail + 1);
    dev->admin_sq_tail = (tail + 1) % 64;

    /* Wait for completion */
    uint64_t timeout = 1000000;  /* 1 second */
    while (timeout > 0) {
        if (dev->admin_cq[dev->admin_cq_head].command_id == cmd_id - 1) {
            if (comp) {
                *comp = dev->admin_cq[dev->admin_cq_head];
            }

            uint16_t status = dev->admin_cq[dev->admin_cq_head].status;
            dev->admin_cq_head = (dev->admin_cq_head + 1) % 64;

            /* Ring completion queue doorbell */
            nvme_write32(dev, dev->admin_cq_doorbell, dev->admin_cq_head);

            /* Check status */
            if ((status >> 1) & 0x7F) {
                return -1;
            }
            return 0;
        }
        udelay(1);
        timeout--;
    }

    return -1;  /* Timeout */
}

/*
 * Identify controller
 */
int nvme_identify_ctrl(nvme_device_t *dev) {
    struct nvme_command cmd = { 0 };
    struct nvme_completion comp;

    cmd.dword0.opcode = NVME_ADMIN_IDENTIFY;
    cmd.dword0.nsid = 0;
    cmd.cdw10 = NVME_IDENTIFY_CTRL;

    uint64_t phys_addr = (uint64_t)&dev->ctrl_data;
    cmd.prp1 = phys_addr;

    if (nvme_admin_command(dev, &cmd, &comp) != 0) {
        return -1;
    }

    boot_printf("  Model: %.40s\n", dev->ctrl_data.mn);
    boot_printf("  Serial: %.20s\n", dev->ctrl_data.sn);
    boot_printf("  Firmware: %.8s\n", dev->ctrl_data.fr);

    /* Get max transfer size */
    dev->max_transfer = 1 << (dev->ctrl_data.mdts);
    if (dev->max_transfer > 8) dev->max_transfer = 8;  /* Cap at 8 * page_size */

    return 0;
}

/*
 * Identify namespace
 */
int nvme_identify_ns(nvme_device_t *dev, uint32_t nsid) {
    struct nvme_command cmd = { 0 };
    struct nvme_completion comp;

    cmd.dword0.opcode = NVME_ADMIN_IDENTIFY;
    cmd.dword0.nsid = nsid;
    cmd.cdw10 = NVME_IDENTIFY_NS;

    uint64_t phys_addr = (uint64_t)&dev->ns_data;
    cmd.prp1 = phys_addr;

    if (nvme_admin_command(dev, &cmd, &comp) != 0) {
        return -1;
    }

    dev->current_ns = nsid;
    dev->ns_count = 1;

    /* Calculate capacity */
    uint8_t flbas = dev->ns_data.flbas & 0x0F;
    uint64_t lba_format = dev->ns_data.lba_format[flbas];
    dev->lba_size = (uint16_t)(lba_format & 0xFFFF);
    dev->capacity = dev->ns_data.nsze * dev->lba_size;

    return 0;
}

/*
 * Create IO submission and completion queues
 */
int nvme_create_io_queues(nvme_device_t *dev, uint32_t queue_size) {
    struct nvme_command cmd;
    struct nvme_completion comp;

    dev->io_queue_size = queue_size;
    dev->io_sq = g_io_sq;
    dev->io_cq = g_io_cq;
    dev->io_sq_tail = 0;
    dev->io_cq_head = 0;
    dev->io_sq_doorbell = 0x1000 + (dev->admin_sq_doorbell + 4);
    dev->io_cq_doorbell = 0x1000 + (dev->admin_cq_doorbell + 4);

    /* Create IO completion queue */
    memset(&cmd, 0, sizeof(cmd));
    cmd.dword0.opcode = NVME_ADMIN_CREATE_CQ;
    cmd.cdw10 = ((queue_size - 1) << 16) | 1;  /* QID=1, QSIZE=queue_size */
    cmd.cdw11 = (1 << 1);  /* Enable interrupts */
    cmd.prp1 = (uint64_t)dev->io_cq;

    if (nvme_admin_command(dev, &cmd, &comp) != 0) {
        return -1;
    }

    /* Create IO submission queue */
    memset(&cmd, 0, sizeof(cmd));
    cmd.dword0.opcode = NVME_ADMIN_CREATE_SQ;
    cmd.cdw10 = ((queue_size - 1) << 16) | 1;  /* QID=1, QSIZE=queue_size */
    cmd.cdw11 = (1 << 16) | 1;  /* PC=1, CQID=1 */
    cmd.prp1 = (uint64_t)dev->io_sq;

    if (nvme_admin_command(dev, &cmd, &comp) != 0) {
        return -1;
    }

    boot_printf(BOOT_LOG_OK "NVMe IO queues created (size=%u)\n", queue_size);
    return 0;
}

/*
 * Read from NVMe namespace
 */
int nvme_io_read(nvme_device_t *dev, uint64_t lba, uint32_t count, void *buffer) {
    struct nvme_command cmd = { 0 };
    struct nvme_completion comp;

    cmd.dword0.opcode = NVME_IO_READ;
    cmd.dword0.nsid = dev->current_ns;
    cmd.cdw10 = (uint32_t)(lba & 0xFFFFFFFF);
    cmd.cdw11 = (uint32_t)((lba >> 32) & 0xFFFFFFFF);
    cmd.cdw12 = count - 1;

    /* Set up PRP */
    nvme_setup_prp(dev, &cmd, (uint64_t)buffer, count * dev->lba_size);

    /* Submit to IO queue */
    uint32_t tail = dev->io_sq_tail;
    dev->io_sq[tail] = cmd;
    __sync_synchronize();
    nvme_write32(dev, dev->io_sq_doorbell, tail + 1);
    dev->io_sq_tail = (tail + 1) % dev->io_queue_size;

    /* Wait for completion */
    uint64_t timeout = 5000000;
    while (timeout > 0) {
        if (dev->io_cq[dev->io_cq_head].command_id == cmd.dword0.command_id) {
            uint16_t status = dev->io_cq[dev->io_cq_head].status;
            dev->io_cq_head = (dev->io_cq_head + 1) % dev->io_queue_size;
            nvme_write32(dev, dev->io_cq_doorbell, dev->io_cq_head);
            return (status >> 1) & 0x7F ? -1 : 0;
        }
        udelay(1);
        timeout--;
    }
    return -1;
}

/*
 * Write to NVMe namespace
 */
int nvme_io_write(nvme_device_t *dev, uint64_t lba, uint32_t count, const void *buffer) {
    struct nvme_command cmd = { 0 };
    struct nvme_completion comp;

    cmd.dword0.opcode = NVME_IO_WRITE;
    cmd.dword0.nsid = dev->current_ns;
    cmd.cdw10 = (uint32_t)(lba & 0xFFFFFFFF);
    cmd.cdw11 = (uint32_t)((lba >> 32) & 0xFFFFFFFF);
    cmd.cdw12 = count - 1;

    nvme_setup_prp(dev, &cmd, (uint64_t)buffer, count * dev->lba_size);

    /* Submit to IO queue */
    uint32_t tail = dev->io_sq_tail;
    dev->io_sq[tail] = cmd;
    __sync_synchronize();
    nvme_write32(dev, dev->io_sq_doorbell, tail + 1);
    dev->io_sq_tail = (tail + 1) % dev->io_queue_size;

    /* Wait for completion */
    uint64_t timeout = 5000000;
    while (timeout > 0) {
        if (dev->io_cq[dev->io_cq_head].command_id == cmd.dword0.command_id) {
            uint16_t status = dev->io_cq[dev->io_cq_head].status;
            dev->io_cq_head = (dev->io_cq_head + 1) % dev->io_queue_size;
            nvme_write32(dev, dev->io_cq_doorbell, dev->io_cq_head);
            return (status >> 1) & 0x7F ? -1 : 0;
        }
        udelay(1);
        timeout--;
    }
    return -1;
}

/*
 * Set up PRP (Physical Region Page) entries for data transfer
 */
void nvme_setup_prp(nvme_device_t *dev, struct nvme_command *cmd,
                     uint64_t phys_addr, uint32_t length) {
    if (length <= dev->page_size) {
        /* Single page */
        cmd->prp1 = phys_addr;
    } else if (length <= dev->page_size * 2) {
        /* Two pages */
        cmd->prp1 = phys_addr;
        cmd->prp2 = phys_addr + dev->page_size;
    } else {
        /* Multiple pages: use PRP list */
        cmd->prp1 = phys_addr;
        /* PRP list pointer */
        static uint64_t prp_list[512] ALIGNED(8);
        uint32_t pages = (length + dev->page_size - 1) / dev->page_size;
        for (uint32_t i = 0; i < pages - 1; i++) {
            prp_list[i] = phys_addr + (i + 1) * dev->page_size;
        }
        cmd->prp2 = (uint64_t)prp_list;
    }
}

/*
 * Flush the NVMe device
 */
int nvme_flush(nvme_device_t *dev) {
    struct nvme_command cmd = { 0 };
    struct nvme_completion comp;

    cmd.dword0.opcode = NVME_IO_FLUSH;
    cmd.dword0.nsid = dev->current_ns;

    uint32_t tail = dev->io_sq_tail;
    dev->io_sq[tail] = cmd;
    __sync_synchronize();
    nvme_write32(dev, dev->io_sq_doorbell, tail + 1);
    dev->io_sq_tail = (tail + 1) % dev->io_queue_size;

    uint64_t timeout = 5000000;
    while (timeout > 0) {
        if (dev->io_cq[dev->io_cq_head].command_id == cmd.dword0.command_id) {
            dev->io_cq_head = (dev->io_cq_head + 1) % dev->io_queue_size;
            nvme_write32(dev, dev->io_cq_doorbell, dev->io_cq_head);
            return 0;
        }
        udelay(1);
        timeout--;
    }
    return -1;
}

/*
 * Initialize NVMe from PCI scan
 */
void nvme_init_from_pci(void) {
    /* Find NVMe controllers (class 01, subclass 08) */
    pci_device_t *pci_dev = NULL;
    int found = 0;

    for (int i = 0; i < pci_get_device_count(); i++) {
        pci_dev = pci_get_device(i);
        if (pci_dev && pci_dev->class_code == 0x01 && pci_dev->subclass == 0x08) {
            if (nvme_init(&g_nvme_dev, pci_dev->bus, pci_dev->device, pci_dev->function) == 0) {
                found = 1;
                break;
            }
        }
    }

    if (!found) {
        boot_printf(BOOT_LOG_WARN "No NVMe controller found\n");
    }
}