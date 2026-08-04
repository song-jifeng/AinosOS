/*
 * AinosOS - drivers/usb.c
 * USB controller driver implementation
 */

#include <types.h>
#include <macros.h>
#include <boot/boot.h>
#include <drivers/pci.h>
#include <drivers/usb.h>

/* Global USB controller */
usb_controller_t g_usb_ctrl = { 0 };

/*
 * Initialize the USB subsystem
 * Finds USB controllers (EHCI/xHCI) on PCI bus
 */
int usb_init(void) {
    boot_printf(BOOT_LOG_INIT "Initializing USB...\n");

    /* Scan for USB controllers on PCI */
    for (int i = 0; i < pci_get_device_count(); i++) {
        pci_device_t *pci_dev = pci_get_device(i);
        if (!pci_dev) continue;

        /* Check for USB controller classes */
        if (pci_dev->class_code == 0x0C) {
            uint8_t prog_if = pci_dev->prog_if;
            int type = -1;

            if (pci_dev->subclass == 0x03) {
                if (prog_if == 0x00) { /* UHCI */ type = 0; }
                else if (prog_if == 0x10) { /* OHCI */ type = 1; }
                else if (prog_if == 0x20) { /* EHCI */ type = 2; }
                else if (prog_if == 0x30) { /* xHCI */ type = 3; }
            }

            if (type >= 0) {
                boot_printf("  USB controller: %02X:%02X.%X type=%d\n",
                            pci_dev->bus, pci_dev->device, pci_dev->function, type);

                /* Read BAR0 */
                uint32_t bar0 = pci_dev->bars[0];
                uint64_t mmio_base;

                if (bar0 & 4) {
                    uint32_t bar1 = pci_dev->bars[1];
                    mmio_base = (uint64_t)(bar0 & ~0xF) | ((uint64_t)bar1 << 32);
                } else if (bar0 & 1) {
                    /* I/O BAR */
                    mmio_base = bar0 & ~0x3;
                } else {
                    mmio_base = bar0 & ~0xF;
                }

                pci_enable_bus_mastering(pci_dev->bus, pci_dev->device, pci_dev->function);
                pci_enable_mmio(pci_dev->bus, pci_dev->device, pci_dev->function);

                usb_controller_init(&g_usb_ctrl, mmio_base, type);
                break;
            }
        }
    }

    if (!g_usb_ctrl.initialized) {
        boot_printf(BOOT_LOG_WARN "No USB controller found\n");
    }

    return g_usb_ctrl.initialized ? 0 : -1;
}

/*
 * Initialize a USB controller
 */
int usb_controller_init(usb_controller_t *ctrl, uint64_t mmio_base, int type) {
    ctrl->mmio_base = mmio_base;
    ctrl->type = type;
    ctrl->port_count = 0;
    ctrl->initialized = 1;

    const char *type_names[] = { "UHCI", "OHCI", "EHCI", "xHCI" };
    if (type >= 0 && type < 4) {
        boot_printf(BOOT_LOG_OK "USB %s at 0x%016llX\n", type_names[type], mmio_base);
    }

    return 0;
}

/*
 * Perform a USB control transfer
 */
int usb_device_control_transfer(usb_device_t *dev, uint8_t bmRequestType,
                                 uint8_t bRequest, uint16_t wValue,
                                 uint16_t wIndex, uint16_t wLength,
                                 void *data) {
    if (!dev) return -1;

    struct usb_device_request req;
    req.bmRequestType = bmRequestType;
    req.bRequest = bRequest;
    req.wValue = wValue;
    req.wIndex = wIndex;
    req.wLength = wLength;

    /* For now, this is a stub - actual implementation requires
     * full EHCI/xHCI register programming */
    /* The hardware-specific implementation would go here */

    return 0;
}

/*
 * Get a USB descriptor from the device
 */
int usb_get_descriptor(usb_device_t *dev, uint8_t type, uint8_t index,
                        void *buffer, uint16_t length) {
    uint8_t bmRequestType = 0x80;  /* Device-to-host, standard, device */
    uint16_t wValue = (uint16_t)((type << 8) | index);

    return usb_device_control_transfer(dev, bmRequestType,
                                       USB_REQ_GET_DESCRIPTOR,
                                       wValue, 0, length, buffer);
}

/*
 * Set the USB device address
 */
int usb_set_address(usb_device_t *dev, uint8_t address) {
    return usb_device_control_transfer(dev, 0x00,  /* Host-to-device, standard, device */
                                       USB_REQ_SET_ADDRESS,
                                       address, 0, 0, NULL);
}

/*
 * Set the USB device configuration
 */
int usb_set_configuration(usb_device_t *dev, uint8_t config) {
    return usb_device_control_transfer(dev, 0x00,
                                       USB_REQ_SET_CONFIGURATION,
                                       config, 0, 0, NULL);
}

/*
 * Enumerate a USB device
 */
int usb_enumerate_device(usb_device_t *dev) {
    if (!dev) return -1;

    /* Get device descriptor (first 8 bytes for max packet size) */
    if (usb_get_descriptor(dev, USB_DESC_DEVICE, 0,
                           &dev->dev_desc, 8) != 0) {
        return -1;
    }

    dev->ep0_max_packet = dev->dev_desc.bMaxPacketSize0;

    /* Set address */
    if (usb_set_address(dev, dev->address) != 0) {
        return -1;
    }

    /* Get full device descriptor */
    if (usb_get_descriptor(dev, USB_DESC_DEVICE, 0,
                           &dev->dev_desc, sizeof(dev->dev_desc)) != 0) {
        return -1;
    }

    boot_printf("  USB Device: Vendor=0x%04X Product=0x%04X\n",
                dev->dev_desc.idVendor, dev->dev_desc.idProduct);
    boot_printf("    Class=0x%02X SubClass=0x%02X Protocol=0x%02X\n",
                dev->dev_desc.bDeviceClass, dev->dev_desc.bDeviceSubClass,
                dev->dev_desc.bDeviceProtocol);

    dev->initialized = 1;
    return 0;
}