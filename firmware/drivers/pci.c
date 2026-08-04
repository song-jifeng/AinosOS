/*
 * AinosOS - drivers/pci.c
 * PCI bus enumeration and configuration
 */

#include <types.h>
#include <macros.h>
#include <arch/x86_64/io.h>
#include <drivers/pci.h>

/* Global PCI device list */
pci_device_t g_pci_devices[256];
int g_pci_device_count = 0;

/*
 * Read a 32-bit value from the PCI configuration space
 */
uint32_t pci_config_read(uint8_t bus, uint8_t dev, uint8_t func, uint8_t reg) {
    uint32_t address = (uint32_t)((bus << 16) | (dev << 11) | (func << 8) | (reg & 0xFC) | 0x80000000);
    io_outl(PCI_CONFIG_ADDR, address);
    return io_inl(PCI_CONFIG_DATA);
}

/*
 * Write a 32-bit value to the PCI configuration space
 */
void pci_config_write(uint8_t bus, uint8_t dev, uint8_t func, uint8_t reg, uint32_t val) {
    uint32_t address = (uint32_t)((bus << 16) | (dev << 11) | (func << 8) | (reg & 0xFC) | 0x80000000);
    io_outl(PCI_CONFIG_ADDR, address);
    io_outl(PCI_CONFIG_DATA, val);
}

/*
 * Read vendor ID
 */
uint16_t pci_read_vendor(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint16_t)(pci_config_read(bus, dev, func, PCI_VENDOR_ID) & 0xFFFF);
}

/*
 * Read device ID
 */
uint16_t pci_read_device_id(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint16_t)(pci_config_read(bus, dev, func, PCI_DEVICE_ID) >> 16);
}

/*
 * Read class code
 */
uint8_t pci_read_class(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint8_t)(pci_config_read(bus, dev, func, PCI_CLASS) >> 24);
}

/*
 * Read subclass
 */
uint8_t pci_read_subclass(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint8_t)(pci_config_read(bus, dev, func, PCI_SUBCLASS) >> 16);
}

/*
 * Read programming interface
 */
uint8_t pci_read_prog_if(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint8_t)(pci_config_read(bus, dev, func, PCI_PROG_IF) >> 8);
}

/*
 * Read revision ID
 */
uint8_t pci_read_revision(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint8_t)(pci_config_read(bus, dev, func, PCI_REVISION_ID) & 0xFF);
}

/*
 * Read header type
 */
uint8_t pci_read_header_type(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint8_t)(pci_config_read(bus, dev, func, PCI_HEADER_TYPE) >> 16);
}

/*
 * Read a BAR value
 */
uint32_t pci_read_bar(uint8_t bus, uint8_t dev, uint8_t func, int bar) {
    if (bar < 0 || bar > 5) return 0;
    return pci_config_read(bus, dev, func, PCI_BAR0 + bar * 4);
}

/*
 * Write command register
 */
void pci_write_command(uint8_t bus, uint8_t dev, uint8_t func, uint16_t cmd) {
    uint32_t val = pci_config_read(bus, dev, func, PCI_COMMAND);
    val &= 0xFFFF0000;
    val |= cmd;
    pci_config_write(bus, dev, func, PCI_COMMAND, val);
}

/*
 * Read command register
 */
uint16_t pci_read_command(uint8_t bus, uint8_t dev, uint8_t func) {
    return (uint16_t)(pci_config_read(bus, dev, func, PCI_COMMAND) & 0xFFFF);
}

/*
 * Find a capability in the PCI capability list
 */
uint8_t pci_find_capability(uint8_t bus, uint8_t dev, uint8_t func, uint8_t cap_id) {
    uint8_t cap_ptr = 0;

    /* Check if capabilities are supported */
    uint16_t status = (uint16_t)(pci_config_read(bus, dev, func, PCI_STATUS) >> 16);
    if (!(status & (1 << 4))) return 0;  /* Capabilities list not supported */

    /* Read capability pointer */
    cap_ptr = (uint8_t)(pci_config_read(bus, dev, func, PCI_CAPABILITIES) & 0xFF);

    /* Walk the list */
    while (cap_ptr != 0) {
        uint32_t cap = pci_config_read(bus, dev, func, cap_ptr);
        uint8_t id = cap & 0xFF;
        if (id == cap_id) return cap_ptr;
        cap_ptr = (cap >> 8) & 0xFF;
    }

    return 0;
}

/*
 * Enable bus mastering
 */
void pci_enable_bus_mastering(uint8_t bus, uint8_t dev, uint8_t func) {
    uint16_t cmd = pci_read_command(bus, dev, func);
    cmd |= PCI_CMD_BUS_MASTER;
    pci_write_command(bus, dev, func, cmd);
}

/*
 * Enable MMIO
 */
void pci_enable_mmio(uint8_t bus, uint8_t dev, uint8_t func) {
    uint16_t cmd = pci_read_command(bus, dev, func);
    cmd |= PCI_CMD_MEM_SPACE;
    pci_write_command(bus, dev, func, cmd);
}

/*
 * Enable I/O space
 */
void pci_enable_io_space(uint8_t bus, uint8_t dev, uint8_t func) {
    uint16_t cmd = pci_read_command(bus, dev, func);
    cmd |= PCI_CMD_IO_SPACE;
    pci_write_command(bus, dev, func, cmd);
}

/*
 * Scan a single PCI function
 */
void pci_scan_function(uint8_t bus, uint8_t dev, uint8_t func) {
    uint16_t vendor = pci_read_vendor(bus, dev, func);
    if (vendor == 0xFFFF) return;  /* No device */

    if (g_pci_device_count >= 256) return;

    pci_device_t *pci_dev = &g_pci_devices[g_pci_device_count];
    pci_dev->bus = bus;
    pci_dev->device = dev;
    pci_dev->function = func;
    pci_dev->vendor_id = vendor;
    pci_dev->device_id = pci_read_device_id(bus, dev, func);
    pci_dev->class_code = pci_read_class(bus, dev, func);
    pci_dev->subclass = pci_read_subclass(bus, dev, func);
    pci_dev->prog_if = pci_read_prog_if(bus, dev, func);
    pci_dev->revision_id = pci_read_revision(bus, dev, func);
    pci_dev->header_type = pci_read_header_type(bus, dev, func);

    /* Read BARs */
    for (int i = 0; i < 6; i++) {
        pci_dev->bars[i] = pci_read_bar(bus, dev, func, i);
    }

    /* Read interrupt info */
    uint32_t int_conf = pci_config_read(bus, dev, func, PCI_INTERRUPT_LINE);
    pci_dev->interrupt_line = int_conf & 0xFF;
    pci_dev->interrupt_pin = (int_conf >> 8) & 0xFF;

    /* Check capabilities */
    pci_dev->cap_pointer = (uint8_t)(pci_config_read(bus, dev, func, PCI_CAPABILITIES) & 0xFF);
    pci_dev->has_msi = pci_find_capability(bus, dev, func, PCI_CAP_MSI) != 0;
    pci_dev->has_msix = pci_find_capability(bus, dev, func, PCI_CAP_MSIX) != 0;
    pci_dev->has_pcie = pci_find_capability(bus, dev, func, PCI_CAP_EXPRESS) != 0;

    g_pci_device_count++;
}

/*
 * Scan a single PCI device
 */
void pci_scan_device(uint8_t bus, uint8_t dev) {
    uint16_t vendor = pci_read_vendor(bus, dev, 0);
    if (vendor == 0xFFFF) return;  /* No device */

    pci_scan_function(bus, dev, 0);

    /* Check if this is a multifunction device */
    uint8_t header_type = pci_read_header_type(bus, dev, 0);
    if (header_type & PCI_HEADER_MULTIFUNC) {
        for (uint8_t func = 1; func < 8; func++) {
            vendor = pci_read_vendor(bus, dev, func);
            if (vendor != 0xFFFF) {
                pci_scan_function(bus, dev, func);
            }
        }
    }
}

/*
 * Scan the entire PCI bus (all 256 buses, 32 devices, 8 functions)
 */
void pci_scan_bus(void) {
    boot_printf(BOOT_LOG_INIT "Scanning PCI buses...\n");

    g_pci_device_count = 0;

    for (uint16_t bus = 0; bus < PCI_MAX_BUSES; bus++) {
        /* Check if bus exists by looking at device 0 */
        uint16_t vendor = pci_read_vendor(bus, 0, 0);
        if (vendor == 0xFFFF && bus > 0) continue;

        for (uint8_t dev = 0; dev < PCI_MAX_DEVICES; dev++) {
            pci_scan_device(bus, dev);
        }
    }

    boot_printf(BOOT_LOG_OK "PCI scan complete: %d devices found\n", g_pci_device_count);
}

/*
 * Get the number of PCI devices found
 */
int pci_get_device_count(void) {
    return g_pci_device_count;
}

/*
 * Get a PCI device by index
 */
pci_device_t *pci_get_device(int index) {
    if (index >= 0 && index < g_pci_device_count) {
        return &g_pci_devices[index];
    }
    return NULL;
}

/*
 * Find a PCI device by vendor/device ID
 */
pci_device_t *pci_find_device(uint16_t vendor, uint16_t device) {
    for (int i = 0; i < g_pci_device_count; i++) {
        if (g_pci_devices[i].vendor_id == vendor &&
            g_pci_devices[i].device_id == device) {
            return &g_pci_devices[i];
        }
    }
    return NULL;
}

/*
 * Find a PCI device by class/subclass
 */
pci_device_t *pci_find_class(uint8_t class_code, uint8_t subclass) {
    for (int i = 0; i < g_pci_device_count; i++) {
        if (g_pci_devices[i].class_code == class_code &&
            g_pci_devices[i].subclass == subclass) {
            return &g_pci_devices[i];
        }
    }
    return NULL;
}

/*
 * Print a single PCI device
 */
void pci_print_device(pci_device_t *dev) {
    const char *class_name = "Unknown";

    switch (dev->class_code) {
        case PCI_CLASS_LEGACY:        class_name = "Legacy"; break;
        case PCI_CLASS_STORAGE:       class_name = "Storage"; break;
        case PCI_CLASS_NETWORK:       class_name = "Network"; break;
        case PCI_CLASS_DISPLAY:       class_name = "Display"; break;
        case PCI_CLASS_MULTIMEDIA:    class_name = "Multimedia"; break;
        case PCI_CLASS_MEMORY:        class_name = "Memory"; break;
        case PCI_CLASS_BRIDGE:        class_name = "Bridge"; break;
        case PCI_CLASS_COMMUNICATION: class_name = "Communication"; break;
        case PCI_CLASS_PERIPHERAL:    class_name = "Peripheral"; break;
        case PCI_CLASS_INPUT:         class_name = "Input"; break;
        case PCI_CLASS_SERIAL:        class_name = "Serial"; break;
        case PCI_CLASS_ENCRYPTION:    class_name = "Encryption"; break;
    }

    boot_printf("  %02X:%02X.%X  %04X:%04X  %s %02X (IF %02X) Rev %02X",
                dev->bus, dev->device, dev->function,
                dev->vendor_id, dev->device_id,
                class_name, dev->subclass, dev->prog_if, dev->revision_id);

    if (dev->has_msi) boot_printf(" MSI");
    if (dev->has_msix) boot_printf(" MSI-X");
    if (dev->has_pcie) boot_printf(" PCIe");
    if (dev->interrupt_pin) boot_printf(" IRQ %d", dev->interrupt_line);

    boot_printf("\n");
}

/*
 * Print all PCI devices
 */
void pci_print_all(void) {
    boot_printf("PCI devices (%d):\n", g_pci_device_count);
    for (int i = 0; i < g_pci_device_count; i++) {
        pci_print_device(&g_pci_devices[i]);
    }
}