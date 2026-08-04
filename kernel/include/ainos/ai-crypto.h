/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Ainos AI Crypto Module - Header
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI-accelerated cryptographic operations providing AES encryption,
 * SHA hashing, random number generation, and key management.
 */

#ifndef _AINOS_AI_CRYPTO_H
#define _AINOS_AI_CRYPTO_H

#include <linux/types.h>
#include <crypto/aes.h>
#include <crypto/sha.h>
#include <crypto/hash.h>
#include <crypto/skcipher.h>
#include <crypto/aead.h>
#include <crypto/akcipher.h>
#include <crypto/kpp.h>
#include <crypto/rng.h>
#include <crypto/engine.h>

/* Module identification */
#define AI_CRYPTO_MODULE_NAME		"ai_crypto"
#define AI_CRYPTO_MODULE_VERSION	"1.0.0"
#define AI_CRYPTO_MODULE_DESC		"Ainos AI Crypto Module"
#define AI_CRYPTO_MODULE_AUTHOR		"Ainos Kernel Team"

/* Device interface */
#define AI_CRYPTO_DEVICE_NAME		"ai-crypto"
#define AI_CRYPTO_CLASS_NAME		"ai-crypto"
#define AI_CRYPTO_MAX_DEVICES		4

/* IOCTL commands */
#define AI_CRYPTO_IOC_MAGIC		0xB2

#define AI_CRYPTO_IOCTL_GET_INFO		_IOR(AI_CRYPTO_IOC_MAGIC, 0x01, struct ai_crypto_info)
#define AI_CRYPTO_IOCTL_AES_ENCRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x02, struct ai_crypto_aes_request)
#define AI_CRYPTO_IOCTL_AES_DECRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x03, struct ai_crypto_aes_request)
#define AI_CRYPTO_IOCTL_SHA256		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x04, struct ai_crypto_hash_request)
#define AI_CRYPTO_IOCTL_SHA512		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x05, struct ai_crypto_hash_request)
#define AI_CRYPTO_IOCTL_GET_RANDOM		_IOR(AI_CRYPTO_IOC_MAGIC, 0x06, struct ai_crypto_random)
#define AI_CRYPTO_IOCTL_KEY_GEN		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x07, struct ai_crypto_key)
#define AI_CRYPTO_IOCTL_KEY_LOAD		_IOW(AI_CRYPTO_IOC_MAGIC, 0x08, struct ai_crypto_key)
#define AI_CRYPTO_IOCTL_KEY_UNLOAD		_IOW(AI_CRYPTO_IOC_MAGIC, 0x09, struct ai_crypto_key)
#define AI_CRYPTO_IOCTL_KEY_DERIVE		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0A, struct ai_crypto_key_derive)
#define AI_CRYPTO_IOCTL_HMAC			_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0B, struct ai_crypto_hmac_request)
#define AI_CRYPTO_IOCTL_AEAD_ENCRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0C, struct ai_crypto_aead_request)
#define AI_CRYPTO_IOCTL_AEAD_DECRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0D, struct ai_crypto_aead_request)
#define AI_CRYPTO_IOCTL_RSA_ENCRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0E, struct ai_crypto_rsa_request)
#define AI_CRYPTO_IOCTL_RSA_DECRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x0F, struct ai_crypto_rsa_request)
#define AI_CRYPTO_IOCTL_RSA_SIGN		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x10, struct ai_crypto_rsa_request)
#define AI_CRYPTO_IOCTL_RSA_VERIFY		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x11, struct ai_crypto_rsa_request)
#define AI_CRYPTO_IOCTL_ECC_GEN		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x12, struct ai_crypto_ecc_request)
#define AI_CRYPTO_IOCTL_ECC_SIGN		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x13, struct ai_crypto_ecc_request)
#define AI_CRYPTO_IOCTL_ECC_VERIFY		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x14, struct ai_crypto_ecc_request)
#define AI_CRYPTO_IOCTL_ECDH			_IOWR(AI_CRYPTO_IOC_MAGIC, 0x15, struct ai_crypto_ecdh_request)
#define AI_CRYPTO_IOCTL_SET_ENGINE		_IOW(AI_CRYPTO_IOC_MAGIC, 0x16, __u32)
#define AI_CRYPTO_IOCTL_GET_ENGINE		_IOR(AI_CRYPTO_IOC_MAGIC, 0x17, __u32)
#define AI_CRYPTO_IOCTL_GET_ALGORITHMS		_IOR(AI_CRYPTO_IOC_MAGIC, 0x18, struct ai_crypto_algorithms)
#define AI_CRYPTO_IOCTL_GET_PERF		_IOR(AI_CRYPTO_IOC_MAGIC, 0x19, struct ai_crypto_perf)
#define AI_CRYPTO_IOCTL_CHACHA20		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x1A, struct ai_crypto_chacha_request)
#define AI_CRYPTO_IOCTL_POLY1305		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x1B, struct ai_crypto_poly1305_request)
#define AI_CRYPTO_IOCTL_GCM_ENCRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x1C, struct ai_crypto_gcm_request)
#define AI_CRYPTO_IOCTL_GCM_DECRYPT		_IOWR(AI_CRYPTO_IOC_MAGIC, 0x1D, struct ai_crypto_gcm_request)

#define AI_CRYPTO_IOC_MAXNR		29

/* AES key sizes */
#define AI_CRYPTO_AES_128_KEY_SIZE	16
#define AI_CRYPTO_AES_192_KEY_SIZE	24
#define AI_CRYPTO_AES_256_KEY_SIZE	32
#define AI_CRYPTO_AES_BLOCK_SIZE	16
#define AI_CRYPTO_AES_IV_SIZE		16

/* SHA digest sizes */
#define AI_CRYPTO_SHA256_DIGEST_SIZE	32
#define AI_CRYPTO_SHA512_DIGEST_SIZE	64
#define AI_CRYPTO_SHA1_DIGEST_SIZE	20
#define AI_CRYPTO_SHA3_256_DIGEST_SIZE	32
#define AI_CRYPTO_SHA3_512_DIGEST_SIZE	64

/* Key types */
enum ai_crypto_key_type {
	AI_CRYPTO_KEY_AES_128		= 0,
	AI_CRYPTO_KEY_AES_192		= 1,
	AI_CRYPTO_KEY_AES_256		= 2,
	AI_CRYPTO_KEY_RSA_2048		= 3,
	AI_CRYPTO_KEY_RSA_4096		= 4,
	AI_CRYPTO_KEY_ECC_P256		= 5,
	AI_CRYPTO_KEY_ECC_P384		= 6,
	AI_CRYPTO_KEY_ECC_P521		= 7,
	AI_CRYPTO_KEY_CHACHA20		= 8,
	AI_CRYPTO_KEY_HMAC_SHA256	= 9,
	AI_CRYPTO_KEY_HMAC_SHA512	= 10,
	AI_CRYPTO_KEY_ED25519		= 11,
	AI_CRYPTO_KEY_X25519		= 12,
};

/* AES cipher modes */
enum ai_crypto_aes_mode {
	AI_CRYPTO_AES_ECB		= 0,
	AI_CRYPTO_AES_CBC		= 1,
	AI_CRYPTO_AES_CTR		= 2,
	AI_CRYPTO_AES_GCM		= 3,
	AI_CRYPTO_AES_CCM		= 4,
	AI_CRYPTO_AES_XTS		= 5,
	AI_CRYPTO_AES_CFB		= 6,
	AI_CRYPTO_AES_OFB		= 7,
	AI_CRYPTO_AES_SIV		= 8,
};

/* Crypto engine types */
enum ai_crypto_engine_type {
	AI_CRYPTO_ENGINE_SOFTWARE	= 0,	/* Software implementation */
	AI_CRYPTO_ENGINE_HARDWARE	= 1,	/* Hardware accelerator */
	AI_CRYPTO_ENGINE_AESNI		= 2,	/* AES-NI instructions */
	AI_CRYPTO_ENGINE_ARM_CE		= 3,	/* ARM Crypto Extensions */
	AI_CRYPTO_ENGINE_AI_OPTIMIZED	= 4,	/* AI-optimized path */
};

/* Hash algorithms */
enum ai_crypto_hash_type {
	AI_CRYPTO_HASH_SHA1		= 0,
	AI_CRYPTO_HASH_SHA256		= 1,
	AI_CRYPTO_HASH_SHA384		= 2,
	AI_CRYPTO_HASH_SHA512		= 3,
	AI_CRYPTO_HASH_SHA3_256		= 4,
	AI_CRYPTO_HASH_SHA3_512		= 5,
	AI_CRYPTO_HASH_BLAKE2S		= 6,
	AI_CRYPTO_HASH_BLAKE2B		= 7,
	AI_CRYPTO_HASH_SM3		= 8,
};

/* AES encrypt/decrypt request */
struct ai_crypto_aes_request {
	__u32			key_id;
	__u32			mode;
	__u32			key_size;
	__u32			flags;
	__u64			src_data;
	__u64			dst_data;
	__u32			src_len;
	__u32			dst_len;
	__u8			iv[AI_CRYPTO_AES_IV_SIZE];
	__u8			aad[64];
	__u32			aad_len;
	__u32			tag_len;
	__s32			result;
	__u32			padding[4];
};

/* Hash request */
struct ai_crypto_hash_request {
	__u32			hash_type;
	__u32			flags;
	__u64			data;
	__u32			data_len;
	__u8			digest[64];
	__u32			digest_len;
	__s32			result;
	__u32			padding[8];
};

/* HMAC request */
struct ai_crypto_hmac_request {
	__u32			key_id;
	__u32			hash_type;
	__u32			flags;
	__u64			data;
	__u32			data_len;
	__u8			mac[64];
	__u32			mac_len;
	__s32			result;
	__u32			padding[8];
};

/* Random number generation */
struct ai_crypto_random {
	__u8			bytes[256];
	__u32			length;
	__u32			flags;
	__u32			entropy_bits;
	__s32			result;
	__u32			padding[4];
};

/* Key management */
struct ai_crypto_key {
	__u32			key_id;
	__u32			key_type;
	__u32			key_size;
	__u32			flags;
	__u8			key_data[512];
	__u8			key_iv[32];
	__u8			key_label[64];
	__u32			key_lifetime_sec;
	__u32			usage_count;
	__u32			max_usage;
	__u32			persistent;
	__s32			result;
	__u32			padding[8];
};

/* Key derivation */
struct ai_crypto_key_derive {
	__u32			base_key_id;
	__u32			new_key_id;
	__u32			new_key_type;
	__u32			derivation_method;
	__u8			context[64];
	__u32			context_len;
	__u8			salt[32];
	__u32			salt_len;
	__u32			iterations;
	__s32			result;
	__u32			padding[8];
};

/* AEAD request */
struct ai_crypto_aead_request {
	__u32			key_id;
	__u32			aead_type;
	__u32			flags;
	__u64			src_data;
	__u64			dst_data;
	__u32			src_len;
	__u32			dst_len;
	__u8			iv[16];
	__u32			iv_len;
	__u8			aad[128];
	__u32			aad_len;
	__u8			tag[16];
	__u32			tag_len;
	__s32			result;
	__u32			padding[4];
};

/* RSA request */
struct ai_crypto_rsa_request {
	__u32			key_id;
	__u32			operation;
	__u32			padding_type;
	__u32			hash_type;
	__u64			input_data;
	__u64			output_data;
	__u32			input_len;
	__u32			output_len;
	__s32			result;
	__u32			padding[8];
};

/* ECC request */
struct ai_crypto_ecc_request {
	__u32			key_id;
	__u32			curve_type;
	__u32			operation;
	__u32			flags;
	__u64			input_data;
	__u64			output_data;
	__u32			input_len;
	__u32			output_len;
	__u8			signature[128];
	__u32			sig_len;
	__s32			result;
	__u32			padding[4];
};

/* ECDH request */
struct ai_crypto_ecdh_request {
	__u32			private_key_id;
	__u32			public_key_id;
	__u32			curve_type;
	__u32			flags;
	__u8			shared_secret[64];
	__u32			secret_len;
	__s32			result;
	__u32			padding[8];
};

/* ChaCha20 request */
struct ai_crypto_chacha_request {
	__u32			key_id;
	__u32			rounds;
	__u32			flags;
	__u8			nonce[12];
	__u32			counter;
	__u64			src_data;
	__u64			dst_data;
	__u32			src_len;
	__u32			dst_len;
	__s32			result;
	__u32			padding[4];
};

/* Poly1305 request */
struct ai_crypto_poly1305_request {
	__u32			key_id;
	__u32			flags;
	__u64			data;
	__u32			data_len;
	__u8			mac[16];
	__s32			result;
	__u32			padding[8];
};

/* GCM request */
struct ai_crypto_gcm_request {
	__u32			key_id;
	__u32			key_size;
	__u32			flags;
	__u8			iv[12];
	__u32			iv_len;
	__u64			src_data;
	__u64			dst_data;
	__u32			src_len;
	__u32			dst_len;
	__u8			aad[128];
	__u32			aad_len;
	__u8			tag[16];
	__u32			tag_len;
	__s32			result;
	__u32			padding[4];
};

/* Supported algorithms */
struct ai_crypto_algorithms {
	__u32			aes_supported;
	__u32			aes_modes;
	__u32			sha_supported;
	__u32			sha_types;
	__u32			rsa_supported;
	__u32			rsa_key_sizes;
	__u32			ecc_supported;
	__u32			ecc_curves;
	__u32			aead_supported;
	__u32			aead_types;
	__u32			chacha_supported;
	__u32			poly1305_supported;
	__u32			hmac_supported;
	__u32			key_derive_supported;
	__u32			hw_accel_supported;
	__u32			max_key_id;
	__u32			padding[8];
};

/* Performance metrics */
struct ai_crypto_perf {
	__u64			aes_encrypt_ops;
	__u64			aes_decrypt_ops;
	__u64			sha256_ops;
	__u64			sha512_ops;
	__u64			rsa_encrypt_ops;
	__u64			rsa_decrypt_ops;
	__u64			ecc_sign_ops;
	__u64			ecc_verify_ops;
	__u64			key_ops;
	__u64			random_bytes_generated;
	__u64			hw_accel_ops;
	__u64			sw_ops;
	__u64			avg_aes_encrypt_ns;
	__u64			avg_aes_decrypt_ns;
	__u64			avg_sha256_ns;
	__u64			avg_sha512_ns;
	__u64			avg_rsa_encrypt_ns;
	__u64			avg_rsa_decrypt_ns;
	__u64			total_ops;
	__u64			total_hw_ops;
	__u64			total_sw_ops;
	__u64			error_count;
	__u32			padding[8];
};

/* Module info */
struct ai_crypto_info {
	char			version[32];
	char			description[64];
	__u32			major_version;
	__u32			minor_version;
	__u32			patch_version;
	__u32			max_keys;
	__u32			active_keys;
	__u32			hw_accel;
	__u32			engine_type;
	__u32			features;
	__u32			padding[8];
};

/* Sysfs entries */
#define AI_CRYPTO_SYSFS_ALGORITHMS		"algorithms"
#define AI_CRYPTO_SYSFS_KEYS			"keys"
#define AI_CRYPTO_SYSFS_ENGINE			"engine"
#define AI_CRYPTO_SYSFS_PERF			"performance"
#define AI_CRYPTO_SYSFS_STATS			"stats"
#define AI_CRYPTO_SYSFS_HW_ACCEL		"hw_accel"
#define AI_CRYPTO_SYSFS_FIPS			"fips_mode"
#define AI_CRYPTO_SYSFS_SEED			"seed"

/* Internal kernel API */
struct ai_crypto_context;

#ifdef CONFIG_AINOS_AI_CRYPTO

/* AES operations */
int ai_crypto_aes_encrypt(struct ai_crypto_aes_request *req);
int ai_crypto_aes_decrypt(struct ai_crypto_aes_request *req);
int ai_crypto_aes_set_key(struct ai_crypto_key *key);

/* Hash operations */
int ai_crypto_sha256(const u8 *data, unsigned int len, u8 *digest);
int ai_crypto_sha512(const u8 *data, unsigned int len, u8 *digest);
int ai_crypto_sha3_256(const u8 *data, unsigned int len, u8 *digest);
int ai_crypto_hash(enum ai_crypto_hash_type type, const u8 *data,
		   unsigned int len, u8 *digest, unsigned int *digest_len);

/* HMAC operations */
int ai_crypto_hmac(enum ai_crypto_hash_type hash_type,
		   const u8 *key, unsigned int key_len,
		   const u8 *data, unsigned int data_len,
		   u8 *mac, unsigned int *mac_len);

/* AEAD operations */
int ai_crypto_aead_encrypt(struct ai_crypto_aead_request *req);
int ai_crypto_aead_decrypt(struct ai_crypto_aead_request *req);

/* RSA operations */
int ai_crypto_rsa_encrypt(struct ai_crypto_rsa_request *req);
int ai_crypto_rsa_decrypt(struct ai_crypto_rsa_request *req);
int ai_crypto_rsa_sign(struct ai_crypto_rsa_request *req);
int ai_crypto_rsa_verify(struct ai_crypto_rsa_request *req);

/* ECC operations */
int ai_crypto_ecc_gen_key(struct ai_crypto_ecc_request *req);
int ai_crypto_ecc_sign(struct ai_crypto_ecc_request *req);
int ai_crypto_ecc_verify(struct ai_crypto_ecc_request *req);
int ai_crypto_ecdh(struct ai_crypto_ecdh_request *req);

/* ChaCha20-Poly1305 */
int ai_crypto_chacha20(struct ai_crypto_chacha_request *req);
int ai_crypto_poly1305(struct ai_crypto_poly1305_request *req);
int ai_crypto_gcm_encrypt(struct ai_crypto_gcm_request *req);
int ai_crypto_gcm_decrypt(struct ai_crypto_gcm_request *req);

/* Random number generation */
int ai_crypto_get_random_bytes(u8 *buf, unsigned int len);
int ai_crypto_get_random_u32(u32 *val);
int ai_crypto_get_random_u64(u64 *val);
int ai_crypto_seed_rng(const u8 *seed, unsigned int len);

/* Key management */
int ai_crypto_key_generate(struct ai_crypto_key *key);
int ai_crypto_key_load(struct ai_crypto_key *key);
int ai_crypto_key_unload(unsigned int key_id);
int ai_crypto_key_derive(struct ai_crypto_key_derive *derive);
int ai_crypto_key_get_info(unsigned int key_id, struct ai_crypto_key *key);

/* Engine management */
int ai_crypto_set_engine(enum ai_crypto_engine_type engine);
int ai_crypto_get_engine(enum ai_crypto_engine_type *engine);

/* Performance and info */
int ai_crypto_get_algorithms(struct ai_crypto_algorithms *algos);
int ai_crypto_get_perf(struct ai_crypto_perf *perf);
int ai_crypto_get_info(struct ai_crypto_info *info);
int ai_crypto_reset_perf_counters(void);

#else /* !CONFIG_AINOS_AI_CRYPTO */

static inline int ai_crypto_aes_encrypt(struct ai_crypto_aes_request *req)
{ return -ENODEV; }

static inline int ai_crypto_aes_decrypt(struct ai_crypto_aes_request *req)
{ return -ENODEV; }

static inline int ai_crypto_aes_set_key(struct ai_crypto_key *key)
{ return -ENODEV; }

static inline int ai_crypto_sha256(const u8 *data, unsigned int len, u8 *d)
{ return -ENODEV; }

static inline int ai_crypto_sha512(const u8 *data, unsigned int len, u8 *d)
{ return -ENODEV; }

static inline int ai_crypto_sha3_256(const u8 *data, unsigned int len, u8 *d)
{ return -ENODEV; }

static inline int ai_crypto_hash(enum ai_crypto_hash_type t, const u8 *data,
				 unsigned int len, u8 *d, unsigned int *dl)
{ return -ENODEV; }

static inline int ai_crypto_hmac(enum ai_crypto_hash_type ht, const u8 *key,
				 unsigned int klen, const u8 *data,
				 unsigned int dlen, u8 *mac, unsigned int *mlen)
{ return -ENODEV; }

static inline int ai_crypto_aead_encrypt(struct ai_crypto_aead_request *req)
{ return -ENODEV; }

static inline int ai_crypto_aead_decrypt(struct ai_crypto_aead_request *req)
{ return -ENODEV; }

static inline int ai_crypto_rsa_encrypt(struct ai_crypto_rsa_request *req)
{ return -ENODEV; }

static inline int ai_crypto_rsa_decrypt(struct ai_crypto_rsa_request *req)
{ return -ENODEV; }

static inline int ai_crypto_rsa_sign(struct ai_crypto_rsa_request *req)
{ return -ENODEV; }

static inline int ai_crypto_rsa_verify(struct ai_crypto_rsa_request *req)
{ return -ENODEV; }

static inline int ai_crypto_ecc_gen_key(struct ai_crypto_ecc_request *req)
{ return -ENODEV; }

static inline int ai_crypto_ecc_sign(struct ai_crypto_ecc_request *req)
{ return -ENODEV; }

static inline int ai_crypto_ecc_verify(struct ai_crypto_ecc_request *req)
{ return -ENODEV; }

static inline int ai_crypto_ecdh(struct ai_crypto_ecdh_request *req)
{ return -ENODEV; }

static inline int ai_crypto_chacha20(struct ai_crypto_chacha_request *req)
{ return -ENODEV; }

static inline int ai_crypto_poly1305(struct ai_crypto_poly1305_request *req)
{ return -ENODEV; }

static inline int ai_crypto_gcm_encrypt(struct ai_crypto_gcm_request *req)
{ return -ENODEV; }

static inline int ai_crypto_gcm_decrypt(struct ai_crypto_gcm_request *req)
{ return -ENODEV; }

static inline int ai_crypto_get_random_bytes(u8 *buf, unsigned int len)
{ return -ENODEV; }

static inline int ai_crypto_get_random_u32(u32 *val)
{ return -ENODEV; }

static inline int ai_crypto_get_random_u64(u64 *val)
{ return -ENODEV; }

static inline int ai_crypto_seed_rng(const u8 *seed, unsigned int len)
{ return -ENODEV; }

static inline int ai_crypto_key_generate(struct ai_crypto_key *key)
{ return -ENODEV; }

static inline int ai_crypto_key_load(struct ai_crypto_key *key)
{ return -ENODEV; }

static inline int ai_crypto_key_unload(unsigned int key_id)
{ return -ENODEV; }

static inline int ai_crypto_key_derive(struct ai_crypto_key_derive *derive)
{ return -ENODEV; }

static inline int ai_crypto_key_get_info(unsigned int key_id,
					 struct ai_crypto_key *key)
{ return -ENODEV; }

static inline int ai_crypto_set_engine(enum ai_crypto_engine_type engine)
{ return -ENODEV; }

static inline int ai_crypto_get_engine(enum ai_crypto_engine_type *engine)
{ return -ENODEV; }

static inline int ai_crypto_get_algorithms(struct ai_crypto_algorithms *algos)
{ return -ENODEV; }

static inline int ai_crypto_get_perf(struct ai_crypto_perf *perf)
{ return -ENODEV; }

static inline int ai_crypto_get_info(struct ai_crypto_info *info)
{ return -ENODEV; }

static inline int ai_crypto_reset_perf_counters(void)
{ return -ENODEV; }

#endif /* CONFIG_AINOS_AI_CRYPTO */

#endif /* _AINOS_AI_CRYPTO_H */