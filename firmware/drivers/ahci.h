/*
 * AinosOS - drivers/ahci.h
 * AHCI (Advanced Host Controller Interface) driver declarations
 */

#ifndef AINOS_DRIVERS_AHCI_H
#define AINOS_DRIVERS_AHCI_H

#include <types.h>

/* AHCI HBA registers */
#define AHCI_CAP                0x00
#define AHCI_GHC                0x04
#define AHCI_IS                 0x08
#define AHCI_PI                 0x0C
#define AHCI_VS                 0x10
#define AHCI_CCC_CTL            0x14
#define AHCI_CCC_PORTS          0x18
#define AHCI_EM_LOC             0x1C
#define AHCI_EM_CTL             0x20
#define AHCI_CAP2               0x24
#define AHCI_BOHC               0x28

/* AHCI GHC bits */
#define AHCI_GHC_AE             (1 << 31)
#define AHCI_GHC_IE             (1 << 1)
#define AHCI_GHC_HR             (1 << 0)

/* AHCI port registers */
#define AHCI_PORT_LBASE         0x00
#define AHCI_PORT_HBASE         0x04
#define AHCI_PORT_FB            0x08
#define AHCI_PORT_IS            0x0C
#define AHCI_PORT_IE            0x10
#define AHCI_PORT_CMD           0x14
#define AHCI_PORT_TFD           0x18
#define AHCI_PORT_SIG           0x1C
#define AHCI_PORT_SSTS          0x20
#define AHCI_PORT_SCTL          0x24
#define AHCI_PORT_SERR          0x28
#define AHCI_PORT_SACT          0x2C
#define AHCI_PORT_CI            0x30
#define AHCI_PORT_SNTF          0x34
#define AHCI_PORT_FBS           0x40
#define AHCI_PORT_DEVSLP        0x44

/* AHCI port command bits */
#define AHCI_CMD_ST             (1 << 0)
#define AHCI_CMD_SUD            (1 << 1)
#define AHCI_CMD_POD            (1 << 2)
#define AHCI_CMD_CLO            (1 << 3)
#define AHCI_CMD_FRE            (1 << 4)
#define AHCI_CMD_CCS_MASK       (0x1F << 8)
#define AHCI_CMD_MPSS           (1 << 13)
#define AHCI_CMD_FR             (1 << 14)
#define AHCI_CMD_CR             (1 << 15)
#define AHCI_CMD_CPD            (1 << 16)
#define AHCI_CMD_ICC_MASK       (0x0F << 28)

/* AHCI port interrupt status bits */
#define AHCI_IS_DHRS           (1 << 0)
#define AHCI_IS_PSS            (1 << 1)
#define AHCI_IS_DSS            (1 << 2)
#define AHCI_IS_SDBS           (1 << 3)
#define AHCI_IS_UFS            (1 << 4)
#define AHCI_IS_DPS            (1 << 5)
#define AHCI_IS_PCS            (1 << 6)
#define AHCI_IS_DMPS           (1 << 7)
#define AHCI_IS_PRCS           (1 << 22)
#define AHCI_IS_IPMS           (1 << 23)
#define AHCI_IS_OFS            (1 << 24)
#define AHCI_IS_INFS           (1 << 26)
#define AHCI_IS_IFS            (1 << 27)
#define AHCI_IS_HBDS           (1 << 28)
#define AHCI_IS_HBFS           (1 << 29)
#define AHCI_IS_TFES           (1 << 30)
#define AHCI_IS_CPDS           (1 << 31)

/* SATA FIS types */
#define SATA_FIS_TYPE_H2D      0x27
#define SATA_FIS_TYPE_D2H      0x34
#define SATA_FIS_TYPE_DMA_ACT  0x39
#define SATA_FIS_TYPE_DMA_SETUP 0x41
#define SATA_FIS_TYPE_DATA     0x46
#define SATA_FIS_TYPE_BIST     0x58
#define SATA_FIS_TYPE_PIO_SETUP 0x5F
#define SATA_FIS_TYPE_DEV_BITS 0xA1

/* ATA commands */
#define ATA_CMD_READ_DMA       0xC8
#define ATA_CMD_READ_DMA_EXT   0x25
#define ATA_CMD_WRITE_DMA      0xCA
#define ATA_CMD_WRITE_DMA_EXT  0x35
#define ATA_CMD_IDENTIFY       0xEC
#define ATA_CMD_FLUSH_CACHE    0xE7
#define ATA_CMD_FLUSH_CACHE_EXT 0xEA
#define ATA_CMD_SET_FEATURES   0xEF
#define ATA_CMD_READ_NATIVE_MAX 0xF8
#define ATA_CMD_SECURITY_FREEZE 0xF5

/* ATA status */
#define ATA_STATUS_ERR         0x01
#define ATA_STATUS_DRQ         0x08
#define ATA_STATUS_SRV         0x10
#define ATA_STATUS_DF          0x20
#define ATA_STATUS_RDY         0x40
#define ATA_STATUS_BSY         0x80

/* Command list structure */
struct PACKED ahci_cmd_header {
    uint16_t cfis_len:5;
    uint16_t atapi:1;
    uint16_t write:1;
    uint16_t prefetchable:1;
    uint16_t reset:1;
    uint16_t bist:1;
    uint16_t clear_busy:1;
    uint16_t reserved:1;
    uint16_t cfl:5;
    uint16_t a:1;
    uint16_t w:1;
    uint16_t p:1;
    uint16_t r:1;
    uint16_t b:1;
    uint16_t c:1;
    uint16_t d:1;
    uint32_t prdtl;
    volatile uint32_t prdbc;
    uint32_t reserved2[2];
};

/* Command list entry */
struct PACKED ahci_cl_entry {
    struct ahci_cmd_header header;
    uint8_t  acmd[0x40];
    uint8_t  reserved[0x20];
    uint64_t prdt[0];
};

/* PRDT entry */
struct PACKED ahci_prdt_entry {
    uint64_t dba;
    uint32_t reserved;
    uint32_t dbc;
};

/* Received FIS structure */
struct PACKED ahci_rfis {
    uint8_t dma_setup[0x1C];
    uint8_t reserved0[0x04];
    uint8_t pio_setup[0x14];
    uint8_t reserved1[0x0C];
    uint8_t d2h_register[0x14];
    uint8_t reserved2[0x0C];
    uint8_t sdbfis[0x08];
    uint8_t ufis[0x40];
    uint8_t reserved3[0x60];
};

/* HBA memory structure */
struct PACKED ahci_hba_mem {
    uint8_t clb[0x400];
    uint8_t fb[0x200];
    uint8_t rfis[0x100];
};

/* AHCI port structure */
typedef struct {
    int initialized;
    uint32_t port_num;
    volatile uint32_t *port_base;
    int present;
    int atapi;
    uint64_t capacity;
    uint32_t sector_size;
    uint32_t max_lba;
    struct ahci_hba_mem *mem;
} ahci_port_t;

/* AHCI controller structure */
typedef struct {
    int initialized;
    uint64_t mmio_base;
    uint32_t port_count;
    ahci_port_t ports[32];
} ahci_device_t;

/* AHCI functions */
int  ahci_init(ahci_device_t *dev, uint64_t mmio_base);
int  ahci_port_init(ahci_device_t *dev, int port_num);
int  ahci_read(ahci_port_t *port, uint64_t lba, uint32_t count, void *buffer);
int  ahci_write(ahci_port_t *port, uint64_t lba, uint32_t count, const void *buffer);
int  ahci_flush(ahci_port_t *port);
int  ahci_identify(ahci_port_t *port);
void ahci_port_stop(ahci_port_t *port);
void ahci_port_start(ahci_port_t *port);
int  ahci_find_controller(void);

/* Global AHCI device */
extern ahci_device_t g_ahci_dev;

#endif /* AINOS_DRIVERS_AHCI_H */