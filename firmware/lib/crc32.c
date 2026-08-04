/*
 * AinosOS - lib/crc32.c
 * CRC32 checksum implementation
 */

#include <types.h>
#include <lib/crc32.h>

/* CRC32 polynomial */
#define CRC32_POLY  0xEDB88320
#define CRC32C_POLY 0x82F63B78

/* Lookup tables */
static uint32_t crc32_table[256];
static uint32_t crc32c_table[256];
static int tables_initialized = 0;

/*
 * Initialize CRC32 lookup table
 */
void crc32_init_table(void) {
    if (tables_initialized) return;

    for (uint32_t i = 0; i < 256; i++) {
        uint32_t crc = i;
        for (int j = 0; j < 8; j++) {
            crc = (crc >> 1) ^ (CRC32_POLY & -(crc & 1));
        }
        crc32_table[i] = crc;

        /* CRC32C */
        crc = i;
        for (int j = 0; j < 8; j++) {
            crc = (crc >> 1) ^ (CRC32C_POLY & -(crc & 1));
        }
        crc32c_table[i] = crc;
    }

    tables_initialized = 1;
}

/*
 * Calculate CRC32 from data
 */
uint32_t crc32(const void *data, size_t length) {
    return crc32_finalize(crc32_update(0, data, length));
}

/*
 * Update CRC32 with new data
 */
uint32_t crc32_update(uint32_t crc, const void *data, size_t length) {
    if (!tables_initialized) crc32_init_table();

    crc = ~crc;
    const uint8_t *bytes = (const uint8_t*)data;

    for (size_t i = 0; i < length; i++) {
        crc = crc32_table[(crc ^ bytes[i]) & 0xFF] ^ (crc >> 8);
    }

    return ~crc;
}

/*
 * Finalize CRC32
 */
uint32_t crc32_finalize(uint32_t crc) {
    return crc;
}

/*
 * Calculate CRC32C (Castagnoli)
 */
uint32_t crc32c(const void *data, size_t length) {
    return crc32c_update(0, data, length);
}

/*
 * Update CRC32C with new data
 */
uint32_t crc32c_update(uint32_t crc, const void *data, size_t length) {
    if (!tables_initialized) crc32_init_table();

    crc = ~crc;
    const uint8_t *bytes = (const uint8_t*)data;

    for (size_t i = 0; i < length; i++) {
        crc = crc32c_table[(crc ^ bytes[i]) & 0xFF] ^ (crc >> 8);
    }

    return ~crc;
}