/*
 * AinosOS - lib/crc32.h
 * CRC32 checksum declarations
 */

#ifndef AINOS_LIB_CRC32_H
#define AINOS_LIB_CRC32_H

#include <types.h>

uint32_t crc32(const void *data, size_t length);
uint32_t crc32_update(uint32_t crc, const void *data, size_t length);
uint32_t crc32_finalize(uint32_t crc);
void crc32_init_table(void);

/* CRC32C (Castagnoli) variant */
uint32_t crc32c(const void *data, size_t length);
uint32_t crc32c_update(uint32_t crc, const void *data, size_t length);

#endif /* AINOS_LIB_CRC32_H */