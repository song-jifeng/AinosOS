/*
 * AinosOS - drivers/nvme.h
 * NVMe (Non-Volatile Memory Express) driver declarations
 */

#ifndef AINOS_DRIVERS_NVME_H
#define AINOS_DRIVERS_NVME_H

#include <types.h>

/* NVMe controller registers */
#define NVME_REG_CAP        0x0000  /* Capabilities */
#define NVME_REG_VS         0x0008  /* Version */
#define NVME_REG_INTMS      0x000C  /* Interrupt Mask Set */
#define NVME_REG_INTMC      0x0010  /* Interrupt Mask Clear */
#define NVME_REG_CC         0x0014  /* Controller Configuration */
#define NVME_REG_CSTS       0x001C  /* Controller Status */
#define NVME_REG_NSSR       0x0020  /* NVM Subsystem Reset */
#define NVME_REG_AQA        0x0024  /* Admin Queue Attributes */
#define NVME_REG_ASQ        0x0028  /* Admin Submission Queue Base */
#define NVME_REG_ACQ        0x0030  /* Admin Completion Queue Base */
#define NVME_REG_CMBLOC     0x0038  /* Controller Memory Buffer Location */
#define NVME_REG_CMBSZ      0x003C  /* Controller Memory Buffer Size */
#define NVME_REG_BPINFO     0x0040  /* Boot Partition Information */
#define NVME_REG_BPRSEL     0x0044  /* Boot Partition Read Select */
#define NVME_REG_BPMBL      0x0048  /* Boot Partition Memory Buffer Loc */
#define NVME_REG_DBS        0x1000  /* Doorbell registers */

/* NVMe controller configuration */
#define NVME_CC_ENABLE      (1 << 0)
#define NVME_CC_CSS_NVM     (0 << 4)
#define NVME_CC_MPS_SHIFT   7
#define NVME_CC_AMS_RR      0x0000
#define NVME_CC_SHN_NORMAL  0x0001
#define NVME_CC_SHN_ABRUPT  0x0002
#define NVME_CC_IOSQES      6
#define NVME_CC_IOCQES      4

/* NVMe controller status */
#define NVME_CSTS_RDY       (1 << 0)
#define NVME_CSTS_CFS       (1 << 1)
#define NVME_CSTS_SHST_MASK (3 << 2)
#define NVME_CSTS_SHST_NORMAL (0 << 2)
#define NVME_CSTS_SHST_OCCUR  (1 << 2)
#define NVME_CSTS_SHST_COMPLETE (2 << 2)
#define NVME_CSTS_PP        (1 << 5)
#define NVME_CSTS_NSSRO     (1 << 6)

/* NVMe queue types */
#define NVME_Q_ADMIN        0
#define NVME_Q_IO           1

/* NVMe command opcodes */
#define NVME_ADMIN_DELETE_SQ      0x00
#define NVME_ADMIN_CREATE_SQ      0x01
#define NVME_ADMIN_DELETE_CQ      0x04
#define NVME_ADMIN_CREATE_CQ      0x05
#define NVME_ADMIN_IDENTIFY       0x06
#define NVME_ADMIN_ABORT          0x08
#define NVME_ADMIN_SET_FEATURES   0x09
#define NVME_ADMIN_GET_FEATURES   0x0A
#define NVME_ADMIN_ASYNC_EVENT    0x0C
#define NVME_ADMIN_NS_MGMT        0x0D
#define NVME_ADMIN_ACTIVATE_FW    0x10
#define NVME_ADMIN_DOWNLOAD_FW    0x11
#define NVME_ADMIN_DEVICE_SELF_TEST 0x14
#define NVME_ADMIN_NS_ATTACHMENT  0x15
#define NVME_ADMIN_KEEP_ALIVE     0x18
#define NVME_ADMIN_DIRECTIVE_SEND 0x19
#define NVME_ADMIN_DIRECTIVE_RECV 0x1A
#define NVME_ADMIN_VIRTUAL_MGMT   0x1C
#define NVME_ADMIN_NVME_MI_SEND   0x1D
#define NVME_ADMIN_NVME_MI_RECV   0x1E
#define NVME_ADMIN_DOORBELL_BUFFER 0x1F
#define NVME_ADMIN_FORMAT_NVM     0x80
#define NVME_ADMIN_SECURITY_SEND  0x81
#define NVME_ADMIN_SECURITY_RECV  0x82
#define NVME_ADMIN_SANITIZE       0x84

/* NVMe IO command opcodes */
#define NVME_IO_FLUSH            0x00
#define NVME_IO_WRITE            0x01
#define NVME_IO_READ             0x02
#define NVME_IO_WRITE_UNCORRECT  0x04
#define NVME_IO_COMPARE           0x05
#define NVME_IO_WRITE_ZEROES     0x08
#define NVME_IO_DATASET_MGMT     0x09

/* NVMe command completion status codes */
#define NVME_SC_SUCCESS          0x00
#define NVME_SC_INVALID_OPCODE   0x01
#define NVME_SC_INVALID_FIELD    0x02
#define NVME_SC_DATA_XFER_ERROR  0x04
#define NVME_SC_ABORTED          0x07

/* Identify CNS values */
#define NVME_IDENTIFY_NS         0x00
#define NVME_IDENTIFY_CTRL       0x01
#define NVME_IDENTIFY_NS_LIST    0x02
#define NVME_IDENTIFY_CTRL_LIST  0x03

/* NVMe command structure (64 bytes) */
struct PACKED nvme_command {
    struct {
        uint8_t  opcode;
        uint8_t  flags;
        uint16_t command_id;
        uint32_t nsid;
    } dword0;
    uint32_t cdw2;
    uint32_t cdw3;
    uint64_t mptr;
    uint64_t prp1;
    uint64_t prp2;
    uint32_t cdw10;
    uint32_t cdw11;
    uint32_t cdw12;
    uint32_t cdw13;
    uint32_t cdw14;
    uint32_t cdw15;
};

/* NVMe completion queue entry (16 bytes) */
struct PACKED nvme_completion {
    uint32_t cdw0;
    uint32_t reserved;
    uint16_t sq_head;
    uint16_t sq_id;
    uint16_t command_id;
    uint16_t status;
};

/* NVMe submission queue entry */
struct PACKED nvme_sq_entry {
    struct nvme_command cmd;
};

/* NVMe identify controller data */
struct PACKED nvme_identify_ctrl {
    uint16_t vid;
    uint16_t ssvid;
    char     sn[20];
    char     mn[40];
    char     fr[8];
    uint8_t  rab;
    uint8_t  ieee[3];
    uint8_t  cmic;
    uint8_t  mdts;
    uint16_t cntlid;
    uint32_t ver;
    uint32_t rt3r;
    uint32_t oaes;
    uint32_t ctratt;
    uint8_t  reserved[512 - 128];
    uint16_t oacs;
    uint8_t  acl;
    uint8_t  aerl;
    uint8_t  frmw;
    uint8_t  lpa;
    uint8_t  elpe;
    uint8_t  npss;
    uint8_t  avscc;
    uint8_t  apsta;
    uint16_t wctemp;
    uint16_t cctemp;
    uint16_t mtfa;
    uint32_t hmpre;
    uint32_t hmmin;
    uint64_t tnvmcap[2];
    uint64_t unvmcap[2];
    uint32_t rpmbs[2];
    uint16_t edstt;
    uint8_t  dsto;
    uint8_t  fwug;
    uint32_t kas;
    uint16_t hctma;
    uint16_t mntmt;
    uint16_t mxtmt;
    uint32_t sanicap;
    uint32_t trds[2];
    uint32_t trdd[2];
    uint8_t  reserved2[512 - 384];
};

/* NVMe identify namespace data */
struct PACKED nvme_identify_ns {
    uint64_t nsze;
    uint64_t ncap;
    uint64_t nuse;
    uint8_t  nsfeat;
    uint8_t  nlbaf;
    uint8_t  flbas;
    uint8_t  mc;
    uint8_t  dpc;
    uint8_t  dps;
    uint8_t  nmic;
    uint8_t  rescap;
    uint8_t  fpi;
    uint8_t  dlfeat;
    uint16_t nawun;
    uint16_t nawupf;
    uint16_t nacwu;
    uint16_t nabspf;
    uint16_t nabspo;
    uint16_t nabsl;
    uint16_t nabslba;
    uint16_t ncfgel;
    uint16_t ncfgn;
    uint64_t lba_format[16];
    uint8_t  reserved[512 - 192];
};

/* NVMe device structure */
typedef struct {
    int initialized;
    uint64_t mmio_base;
    uint16_t vendor_id;
    uint16_t device_id;
    uint8_t bus;
    uint8_t dev;
    uint8_t func;

    /* Controller info */
    struct nvme_identify_ctrl ctrl_data;
    uint32_t max_transfer;
    uint32_t page_size;
    uint64_t capacity;
    uint32_t lba_size;

    /* Admin queues */
    struct nvme_command *admin_sq;
    struct nvme_completion *admin_cq;
    uint32_t admin_sq_doorbell;
    uint32_t admin_cq_doorbell;
    volatile int admin_sq_tail;
    volatile int admin_cq_head;

    /* IO queues */
    struct nvme_command *io_sq;
    struct nvme_completion *io_cq;
    uint32_t io_sq_doorbell;
    uint32_t io_cq_doorbell;
    volatile int io_sq_tail;
    volatile int io_cq_head;
    uint32_t io_queue_size;

    /* Namespace info */
    uint32_t ns_count;
    uint32_t current_ns;
    struct nvme_identify_ns ns_data;
} nvme_device_t;

/* NVMe functions */
int nvme_init(nvme_device_t *dev, uint8_t bus, uint8_t dev_num, uint8_t func);
int nvme_admin_command(nvme_device_t *dev, struct nvme_command *cmd,
                        struct nvme_completion *comp);
int nvme_io_read(nvme_device_t *dev, uint64_t lba, uint32_t count, void *buffer);
int nvme_io_write(nvme_device_t *dev, uint64_t lba, uint32_t count, const void *buffer);
int nvme_identify_ctrl(nvme_device_t *dev);
int nvme_identify_ns(nvme_device_t *dev, uint32_t nsid);
int nvme_create_io_queues(nvme_device_t *dev, uint32_t queue_size);
void nvme_setup_prp(nvme_device_t *dev, struct nvme_command *cmd,
                     uint64_t phys_addr, uint32_t length);
int nvme_flush(nvme_device_t *dev);

/* Global NVMe device */
extern nvme_device_t g_nvme_dev;

#endif /* AINOS_DRIVERS_NVME_H */