/*
 * AinosOS - drivers/usb.h
 * USB controller driver declarations
 */

#ifndef AINOS_DRIVERS_USB_H
#define AINOS_DRIVERS_USB_H

#include <types.h>

/* USB device speeds */
#define USB_SPEED_LOW       1
#define USB_SPEED_FULL      2
#define USB_SPEED_HIGH      3
#define USB_SPEED_SUPER     4

/* USB transfer types */
#define USB_TRANSFER_CONTROL    0
#define USB_TRANSFER_ISOCHRONOUS 1
#define USB_TRANSFER_BULK       2
#define USB_TRANSFER_INTERRUPT  3

/* Standard USB device requests */
#define USB_REQ_GET_STATUS          0x00
#define USB_REQ_CLEAR_FEATURE       0x01
#define USB_REQ_SET_FEATURE         0x03
#define USB_REQ_SET_ADDRESS         0x05
#define USB_REQ_GET_DESCRIPTOR      0x06
#define USB_REQ_SET_DESCRIPTOR      0x07
#define USB_REQ_GET_CONFIGURATION   0x08
#define USB_REQ_SET_CONFIGURATION   0x09
#define USB_REQ_GET_INTERFACE       0x0A
#define USB_REQ_SET_INTERFACE       0x0B
#define USB_REQ_SYNCH_FRAME         0x0C

/* USB descriptor types */
#define USB_DESC_DEVICE             1
#define USB_DESC_CONFIGURATION      2
#define USB_DESC_STRING             3
#define USB_DESC_INTERFACE          4
#define USB_DESC_ENDPOINT           5
#define USB_DESC_DEVICE_QUALIFIER   6
#define USB_DESC_HID                0x21

/* USB device request structure */
struct PACKED usb_device_request {
    uint8_t  bmRequestType;
    uint8_t  bRequest;
    uint16_t wValue;
    uint16_t wIndex;
    uint16_t wLength;
};

/* USB device descriptor */
struct PACKED usb_device_descriptor {
    uint8_t  bLength;
    uint8_t  bDescriptorType;
    uint16_t bcdUSB;
    uint8_t  bDeviceClass;
    uint8_t  bDeviceSubClass;
    uint8_t  bDeviceProtocol;
    uint8_t  bMaxPacketSize0;
    uint16_t idVendor;
    uint16_t idProduct;
    uint16_t bcdDevice;
    uint8_t  iManufacturer;
    uint8_t  iProduct;
    uint8_t  iSerialNumber;
    uint8_t  bNumConfigurations;
};

/* USB configuration descriptor */
struct PACKED usb_config_descriptor {
    uint8_t  bLength;
    uint8_t  bDescriptorType;
    uint16_t wTotalLength;
    uint8_t  bNumInterfaces;
    uint8_t  bConfigurationValue;
    uint8_t  iConfiguration;
    uint8_t  bmAttributes;
    uint8_t  bMaxPower;
};

/* USB interface descriptor */
struct PACKED usb_interface_descriptor {
    uint8_t  bLength;
    uint8_t  bDescriptorType;
    uint8_t  bInterfaceNumber;
    uint8_t  bAlternateSetting;
    uint8_t  bNumEndpoints;
    uint8_t  bInterfaceClass;
    uint8_t  bInterfaceSubClass;
    uint8_t  bInterfaceProtocol;
    uint8_t  iInterface;
};

/* USB endpoint descriptor */
struct PACKED usb_endpoint_descriptor {
    uint8_t  bLength;
    uint8_t  bDescriptorType;
    uint8_t  bEndpointAddress;
    uint8_t  bmAttributes;
    uint16_t wMaxPacketSize;
    uint8_t  bInterval;
};

/* USB device structure */
typedef struct usb_device {
    int      port;
    int      address;
    int      speed;
    int      initialized;
    struct usb_device_descriptor dev_desc;
    struct usb_config_descriptor *config_desc;
    struct usb_interface_descriptor *iface_desc;
    struct usb_endpoint_descriptor *ep_desc;
    int      ep_count;
    uint8_t  ep0_max_packet;
} usb_device_t;

/* USB controller (EHCI/xHCI) */
typedef struct {
    int      initialized;
    int      type;  /* 0 = EHCI, 1 = xHCI */
    uint64_t mmio_base;
    int      irq;
    int      port_count;
    usb_device_t devices[16];
} usb_controller_t;

/* USB functions */
int usb_init(void);
int usb_controller_init(usb_controller_t *ctrl, uint64_t mmio_base, int type);
int usb_device_control_transfer(usb_device_t *dev, uint8_t bmRequestType,
                                 uint8_t bRequest, uint16_t wValue,
                                 uint16_t wIndex, uint16_t wLength,
                                 void *data);
int usb_get_descriptor(usb_device_t *dev, uint8_t type, uint8_t index,
                        void *buffer, uint16_t length);
int usb_set_address(usb_device_t *dev, uint8_t address);
int usb_set_configuration(usb_device_t *dev, uint8_t config);
int usb_enumerate_device(usb_device_t *dev);

/* Global USB controller */
extern usb_controller_t g_usb_ctrl;

#endif /* AINOS_DRIVERS_USB_H */