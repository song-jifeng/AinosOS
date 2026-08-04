/*
 * AinosOS - drivers/pci.h
 * PCI bus enumeration and configuration declarations
 */

#ifndef AINOS_DRIVERS_PCI_H
#define AINOS_DRIVERS_PCI_H

#include <types.h>

/* PCI configuration space I/O ports */
#define PCI_CONFIG_ADDR     0xCF8
#define PCI_CONFIG_DATA     0xCFC

/* PCI configuration registers */
#define PCI_VENDOR_ID       0x00
#define PCI_DEVICE_ID       0x02
#define PCI_COMMAND         0x04
#define PCI_STATUS          0x06
#define PCI_REVISION_ID     0x08
#define PCI_PROG_IF         0x09
#define PCI_SUBCLASS        0x0A
#define PCI_CLASS           0x0B
#define PCI_CACHE_LINE      0x0C
#define PCI_LATENCY_TIMER   0x0D
#define PCI_HEADER_TYPE     0x0E
#define PCI_BIST            0x0F
#define PCI_BAR0            0x10
#define PCI_BAR1            0x14
#define PCI_BAR2            0x18
#define PCI_BAR3            0x1C
#define PCI_BAR4            0x20
#define PCI_BAR5            0x24
#define PCI_CARDBUS_CIS     0x28
#define PCI_SUBSYSTEM_VENDOR 0x2C
#define PCI_SUBSYSTEM_ID    0x2E
#define PCI_EXP_ROM         0x30
#define PCI_CAPABILITIES    0x34
#define PCI_INTERRUPT_LINE  0x3C
#define PCI_INTERRUPT_PIN   0x3D
#define PCI_MIN_GNT         0x3E
#define PCI_MAX_LAT         0x3F

/* PCI command register bits */
#define PCI_CMD_IO_SPACE        (1 << 0)
#define PCI_CMD_MEM_SPACE       (1 << 1)
#define PCI_CMD_BUS_MASTER      (1 << 2)
#define PCI_CMD_SPECIAL_CYCLES  (1 << 3)
#define PCI_CMD_MEM_WRITE_INV   (1 << 4)
#define PCI_CMD_VGA_PALETTE     (1 << 5)
#define PCI_CMD_PARITY_ERROR    (1 << 6)
#define PCI_CMD_WAIT_CYCLE      (1 << 7)
#define PCI_CMD_SERR            (1 << 8)
#define PCI_CMD_FAST_BACK       (1 << 9)
#define PCI_CMD_INT_DISABLE     (1 << 10)

/* PCI class codes */
#define PCI_CLASS_LEGACY        0x00
#define PCI_CLASS_STORAGE       0x01
#define PCI_CLASS_NETWORK       0x02
#define PCI_CLASS_DISPLAY       0x03
#define PCI_CLASS_MULTIMEDIA    0x04
#define PCI_CLASS_MEMORY        0x05
#define PCI_CLASS_BRIDGE        0x06
#define PCI_CLASS_COMMUNICATION 0x07
#define PCI_CLASS_PERIPHERAL    0x08
#define PCI_CLASS_INPUT         0x09
#define PCI_CLASS_DOCK          0x0A
#define PCI_CLASS_PROCESSOR     0x0B
#define PCI_CLASS_SERIAL        0x0C
#define PCI_CLASS_WIRELESS      0x0D
#define PCI_CLASS_INTELLIGENT   0x0E
#define PCI_CLASS_SATELLITE     0x0F
#define PCI_CLASS_ENCRYPTION    0x10
#define PCI_CLASS_SIGNAL        0x11
#define PCI_CLASS_DPIO          0x12
#define PCI_CLASS_COPROCESSOR   0x40
#define PCI_CLASS_UNCLASSIFIED  0xFF

/* PCI header types */
#define PCI_HEADER_NORMAL       0x00
#define PCI_HEADER_BRIDGE       0x01
#define PCI_HEADER_CARDBUS      0x02
#define PCI_HEADER_MULTIFUNC    0x80

/* BAR types */
#define PCI_BAR_TYPE_MEMORY     0x00
#define PCI_BAR_TYPE_IO         0x01
#define PCI_BAR_MEM_64BIT       0x04
#define PCI_BAR_MEM_PREFETCH    0x08

/* PCI capability IDs */
#define PCI_CAP_PM              0x01
#define PCI_CAP_AGP             0x02
#define PCI_CAP_VPD             0x03
#define PCI_CAP_SLOTID          0x04
#define PCI_CAP_MSI             0x05
#define PCI_CAP_CPCI_HOTSWAP    0x06
#define PCI_CAP_PCIX            0x07
#define PCI_CAP_HT              0x08
#define PCI_CAP_VENDOR          0x09
#define PCI_CAP_DEBUG           0x0A
#define PCI_CAP_CCRS            0x0B
#define PCI_CAP_HOTPLUG         0x0C
#define PCI_CAP_SSVID           0x0D
#define PCI_CAP_AGP3            0x0E
#define PCI_CAP_SECURE          0x0F
#define PCI_CAP_EXPRESS         0x10
#define PCI_CAP_MSIX            0x11
#define PCI_CAP_SATA            0x12
#define PCI_CAP_AF              0x13
#define PCI_CAP_FLR             0x14

/* Maximum devices to scan */
#define PCI_MAX_BUSES           256
#define PCI_MAX_DEVICES         32
#define PCI_MAX_FUNCTIONS       8

/* PCI device structure */
typedef struct {
    uint8_t bus;
    uint8_t device;
    uint8_t function;
    uint16_t vendor_id;
    uint16_t device_id;
    uint8_t class_code;
    uint8_t subclass;
    uint8_t prog_if;
    uint8_t revision_id;
    uint8_t header_type;
    uint8_t interrupt_line;
    uint8_t interrupt_pin;
    uint32_t bars[6];
    uint8_t cap_pointer;
    int has_msi;
    int has_msix;
    int has_pcie;
} pci_device_t;

/* PCI functions */
uint32_t pci_config_read(uint8_t bus, uint8_t dev, uint8_t func, uint8_t reg);
void pci_config_write(uint8_t bus, uint8_t dev, uint8_t func, uint8_t reg, uint32_t val);
uint16_t pci_read_vendor(uint8_t bus, uint8_t dev, uint8_t func);
uint16_t pci_read_device_id(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_read_class(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_read_subclass(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_read_prog_if(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_read_revision(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_read_header_type(uint8_t bus, uint8_t dev, uint8_t func);
uint32_t pci_read_bar(uint8_t bus, uint8_t dev, uint8_t func, int bar);
void pci_write_command(uint8_t bus, uint8_t dev, uint8_t func, uint16_t cmd);
uint16_t pci_read_command(uint8_t bus, uint8_t dev, uint8_t func);
uint8_t pci_find_capability(uint8_t bus, uint8_t dev, uint8_t func, uint8_t cap_id);
void pci_enable_bus_mastering(uint8_t bus, uint8_t dev, uint8_t func);
void pci_enable_mmio(uint8_t bus, uint8_t dev, uint8_t func);
void pci_enable_io_space(uint8_t bus, uint8_t dev, uint8_t func);
void pci_scan_bus(void);
void pci_scan_device(uint8_t bus, uint8_t dev);
void pci_scan_function(uint8_t bus, uint8_t dev, uint8_t func);
int pci_get_device_count(void);
pci_device_t *pci_get_device(int index);
pci_device_t *pci_find_device(uint16_t vendor, uint16_t device);
pci_device_t *pci_find_class(uint8_t class_code, uint8_t subclass);
void pci_print_device(pci_device_t *dev);
void pci_print_all(void);

/* Global PCI device list */
extern pci_device_t g_pci_devices[256];
extern int g_pci_device_count;

#endif /* AINOS_DRIVERS_PCI_H */