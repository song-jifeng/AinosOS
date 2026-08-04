/*
 * AinosOS - lib/hash.h
 * Hash table and hash function implementations
 */

#ifndef AINOS_LIB_HASH_H
#define AINOS_LIB_HASH_H

#include <types.h>
#include <lib/list.h>

/* Hash table entry */
struct hash_entry {
    struct list_node list;
    uint64_t key;
};

/* Hash table structure */
struct hash_table {
    struct list_node *buckets;
    size_t bucket_count;
    size_t entry_count;
};

/* Hash function types */
typedef uint64_t (*hash_func_t)(const void *data, size_t len);
typedef uint64_t (*hash_key_func_t)(uint64_t key);

/* Hash table operations */
int  hash_table_init(struct hash_table *table, size_t bucket_count);
void hash_table_destroy(struct hash_table *table);
void hash_table_insert(struct hash_table *table, struct hash_entry *entry, uint64_t key);
void hash_table_remove(struct hash_table *table, struct hash_entry *entry);
struct hash_entry *hash_table_lookup(const struct hash_table *table, uint64_t key);
void hash_table_clear(struct hash_table *table);
size_t hash_table_size(const struct hash_table *table);

/* Hash functions */
uint64_t hash_djb2(const void *data, size_t len);
uint64_t hash_sdbm(const void *data, size_t len);
uint64_t hash_fnv1a(const void *data, size_t len);
uint64_t hash_crc32(const void *data, size_t len);
uint64_t hash_xor(const void *data, size_t len);
uint64_t hash_murmur3_32(const void *data, size_t len);

/* Inline hash function for 64-bit integers */
static inline uint64_t hash_uint64(uint64_t key) {
    key = (~key) + (key << 18);
    key = key ^ (key >> 31);
    key = key * 21;
    key = key ^ (key >> 11);
    key = key + (key << 6);
    key = key ^ (key >> 22);
    return key;
}

/* Hash table iterator */
#define hash_table_for_each(entry, table) \
    for (size_t _i = 0; _i < (table)->bucket_count; _i++) \
        list_for_each_entry(entry, &(table)->buckets[_i], list)

/* Get hash table load factor */
static inline double hash_table_load_factor(const struct hash_table *table) {
    if (table->bucket_count == 0) return 0;
    return (double)table->entry_count / (double)table->bucket_count;
}

#endif /* AINOS_LIB_HASH_H */