// SPDX-License-Identifier: GPL-2.0-only
/*
 * Ainos AI Crypto Module - Main Module
 *
 * Copyright (C) 2026 Ainos Corporation
 * Authors: Ainos Kernel Team
 *
 * AI-accelerated cryptographic operations providing AES encryption,
 * SHA hashing, random number generation, key management, and
 * support for asymmetric cryptography.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/slab.h>
#include <linux/crypto.h>
#include <crypto/aes.h>
#include <crypto/sha.h>
#include <crypto/hash.h>
#include <crypto/skcipher.h>
#include <crypto/aead.h>
#include <crypto/akcipher.h>
#include <crypto/kpp.h>
#include <crypto/rng.h>
#include <crypto/engine.h>
#include <crypto/internal/skcipher.h>
#include <crypto/algapi.h>
#include <crypto/scatterwalk.h>
#include <linux/string.h>
#include <linux/uaccess.h>
#include <linux/errno.h>
#include <linux/types.h>
#include <linux/mutex.h>
#include <linux/spinlock.h>
#include <linux/atomic.h>
#include <linux/ktime.h>
#include <linux/sysfs.h>
#include <linux/kobject.h>
#include <linux/random.h>
#include <linux/scatterlist.h>
#include <linux/highmem.h>
#include <linux/mm.h>
#include <linux/crypto.h>
#include <crypto/hash.h>
#include <crypto/aead.h>
#include <linux/keyslot-manager.h>

#include "ainos/ai-crypto.h"

MODULE_LICENSE("GPL");
MODULE_VERSION(AI_CRYPTO_MODULE_VERSION);
MODULE_DESCRIPTION(AI_CRYPTO_MODULE_DESC);
MODULE_AUTHOR(AI_CRYPTO_MODULE_AUTHOR);
MODULE_ALIAS("ainos-ai-crypto");

#define ai_crypto_dbg(fmt, ...) \
	pr_debug("ai_crypto: " fmt, ##__VA_ARGS__)
#define ai_crypto_info(fmt, ...) \
	pr_info("ai_crypto: " fmt, ##__VA_ARGS__)
#define ai_crypto_warn(fmt, ...) \
	pr_warn("ai_crypto: " fmt, ##__VA_ARGS__)
#define ai_crypto_err(fmt, ...) \
	pr_err("ai_crypto: " fmt, ##__VA_ARGS__)

static unsigned int crypto_debug;
module_param(crypto_debug, uint, 0644);
static unsigned int hw_accel = 1;
module_param(hw_accel, uint, 0644);
MODULE_PARM_DESC(hw_accel, "Enable hardware acceleration (0=off, 1=on)");
static unsigned int fips_mode;
module_param(fips_mode, uint, 0644);
MODULE_PARM_DESC(fips_mode, "FIPS 140-3 compliance mode (0=off, 1=on)");

/*
 * Key slot structure
 */
struct ai_crypto_key_slot {
	unsigned int		key_id;
	enum ai_crypto_key_type	key_type;
	unsigned int		key_size;
	u8			key_data[512];
	u8			key_iv[32];
	u8			label[64];
	u32			usage_count;
	u32			max_usage;
	u32			lifetime_sec;
	unsigned long		created_jiffies;
	bool			persistent;
	bool			in_use;
	spinlock_t		lock;
};

/*
 * Crypto device context
 */
struct ai_crypto_device {
	struct cdev		cdev;
	struct device		*device;
	struct kobject		*kobj;

	unsigned int		dev_id;
	char			name[64];
	bool			active;

	/* Key store */
	struct ai_crypto_key_slot key_slots[64];
	unsigned int		nr_keys;
	struct mutex		key_mutex;

	/* Engine */
	enum ai_crypto_engine_type engine_type;
	bool			hw_accel_enabled;

	/* Performance counters */
	struct ai_crypto_perf	perf;
	spinlock_t		perf_lock;

	/* Supported algorithms */
	struct ai_crypto_algorithms algorithms;

	/* FIPS mode */
	bool			fips_active;

	/* List */
	struct list_head	list;
};

static dev_t ai_crypto_devno;
static struct class *ai_crypto_class;
static struct list_head ai_crypto_devices;
static struct mutex ai_crypto_global_mutex;
static atomic_t ai_crypto_device_count;
static unsigned int ai_crypto_major;
static struct kmem_cache *ai_crypto_device_cache;

/*
 * Key management
 */

static int ai_crypto_key_slot_alloc(struct ai_crypto_device *dev,
				    struct ai_crypto_key *key)
{
	int i;

	mutex_lock(&dev->key_mutex);
	for (i = 0; i < 64; i++) {
		if (!dev->key_slots[i].in_use) {
			struct ai_crypto_key_slot *slot = &dev->key_slots[i];

			memset(slot, 0, sizeof(*slot));
			spin_lock_init(&slot->lock);
			slot->key_id = i + 1;
			slot->key_type = key->key_type;
			slot->key_size = min_t(u32, key->key_size,
					      sizeof(slot->key_data));
			memcpy(slot->key_data, key->key_data, slot->key_size);
			if (key->key_iv[0] || key->key_iv[1])
				memcpy(slot->key_iv, key->key_iv,
				       sizeof(slot->key_iv));
			strscpy(slot->label, key->key_label,
				sizeof(slot->label));
			slot->usage_count = 0;
			slot->max_usage = key->max_usage;
			slot->lifetime_sec = key->key_lifetime_sec;
			slot->created_jiffies = jiffies;
			slot->persistent = key->persistent;
			slot->in_use = true;

			dev->nr_keys++;
			key->key_id = slot->key_id;
			key->result = 0;

			mutex_unlock(&dev->key_mutex);
			ai_crypto_dbg("Key slot %d allocated (type=%d size=%u)\n",
				     slot->key_id, key->key_type,
				     key->key_size);
			return 0;
		}
	}
	mutex_unlock(&dev->key_mutex);

	return -ENOSPC;
}

static struct ai_crypto_key_slot *ai_crypto_key_slot_find(
		struct ai_crypto_device *dev, unsigned int key_id)
{
	if (key_id == 0 || key_id > 64)
		return NULL;

	if (!dev->key_slots[key_id - 1].in_use)
		return NULL;

	return &dev->key_slots[key_id - 1];
}

static int ai_crypto_key_slot_free(struct ai_crypto_device *dev,
				   unsigned int key_id)
{
	struct ai_crypto_key_slot *slot;

	if (key_id == 0 || key_id > 64)
		return -EINVAL;

	slot = &dev->key_slots[key_id - 1];
	if (!slot->in_use)
		return -ENOENT;

	mutex_lock(&dev->key_mutex);
	memset(slot, 0, sizeof(*slot));
	slot->in_use = false;
	dev->nr_keys--;
	mutex_unlock(&dev->key_mutex);

	ai_crypto_dbg("Key slot %d freed\n", key_id);
	return 0;
}

/*
 * AES operations
 */

static int ai_crypto_do_aes_cipher(struct crypto_sync_skcipher *tfm,
				   const u8 *src, u8 *dst, unsigned int len,
				   const u8 *iv, int encrypt)
{
	SKCIPHER_REQUEST_ON_STACK(req, tfm);
	struct scatterlist sg_src, sg_dst;
	int ret;

	sg_init_one(&sg_src, src, len);
	sg_init_one(&sg_dst, dst, len);

	skcipher_request_set_sync_tfm(req, tfm);
	skcipher_request_set_callback(req, 0, NULL, NULL);
	skcipher_request_set_crypt(req, &sg_src, &sg_dst, len, iv);

	if (encrypt)
		ret = crypto_skcipher_encrypt(req);
	else
		ret = crypto_skcipher_decrypt(req);

	skcipher_request_zero(req);
	return ret;
}

/*
 * SHA operations
 */

static int ai_crypto_do_hash(const char *alg_name, const u8 *data,
			     unsigned int data_len, u8 *digest,
			     unsigned int digest_len)
{
	struct crypto_shash *tfm;
	unsigned int size;
	int ret;

	tfm = crypto_alloc_shash(alg_name, 0, 0);
	if (IS_ERR(tfm))
		return PTR_ERR(tfm);

	size = crypto_shash_digestsize(tfm);
	if (digest_len < size) {
		ret = -EINVAL;
		goto out;
	}

	ret = crypto_shash_tfm_digest(tfm, data, data_len, digest);

out:
	crypto_free_shash(tfm);
	return ret;
}

/*
 * Random number generation
 */

static int ai_crypto_get_random(struct ai_crypto_device *dev, u8 *buf,
				unsigned int len)
{
	get_random_bytes(buf, len);

	spin_lock(&dev->perf_lock);
	dev->perf.random_bytes_generated += len;
	spin_unlock(&dev->perf_lock);

	return 0;
}

/*
 * Device file operations
 */

static int ai_crypto_open(struct inode *inode, struct file *file)
{
	struct ai_crypto_device *dev = container_of(inode->i_cdev,
						   struct ai_crypto_device,
						   cdev);
	if (!dev || !dev->active)
		return -ENODEV;
	file->private_data = dev;
	return 0;
}

static int ai_crypto_release(struct inode *inode, struct file *file)
{
	return 0;
}

static long ai_crypto_ioctl(struct file *file, unsigned int cmd,
			    unsigned long arg)
{
	struct ai_crypto_device *dev = file->private_data;
	void __user *argp = (void __user *)arg;
	struct ai_crypto_info info;
	struct ai_crypto_aes_request aes_req;
	struct ai_crypto_hash_request hash_req;
	struct ai_crypto_random rand_req;
	struct ai_crypto_key key;
	struct ai_crypto_key_derive derive;
	struct ai_crypto_hmac_request hmac_req;
	struct ai_crypto_aead_request aead_req;
	struct ai_crypto_rsa_request rsa_req;
	struct ai_crypto_ecc_request ecc_req;
	struct ai_crypto_ecdh_request ecdh_req;
	struct ai_crypto_algorithms algos;
	struct ai_crypto_perf perf;
	struct ai_crypto_chacha_request chacha_req;
	struct ai_crypto_poly1305_request poly1305_req;
	struct ai_crypto_gcm_request gcm_req;
	struct ai_crypto_key_slot *slot;
	u8 stack_buf[4096];
	u8 *buf = NULL;
	int ret = 0;

	if (!dev || !dev->active)
		return -ENODEV;

	if (_IOC_TYPE(cmd) != AI_CRYPTO_IOC_MAGIC)
		return -ENOTTY;
	if (_IOC_NR(cmd) > AI_CRYPTO_IOC_MAXNR)
		return -ENOTTY;

	switch (cmd) {
	case AI_CRYPTO_IOCTL_GET_INFO:
		memset(&info, 0, sizeof(info));
		strscpy(info.version, AI_CRYPTO_MODULE_VERSION,
			sizeof(info.version));
		strscpy(info.description, AI_CRYPTO_MODULE_DESC,
			sizeof(info.description));
		info.major_version = 1;
		info.minor_version = 0;
		info.patch_version = 0;
		info.max_keys = 64;
		info.active_keys = dev->nr_keys;
		info.hw_accel = dev->hw_accel_enabled;
		info.engine_type = dev->engine_type;
		info.features = 0xFF;

		if (copy_to_user(argp, &info, sizeof(info)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_AES_ENCRYPT:
		if (copy_from_user(&aes_req, argp, sizeof(aes_req))) {
			ret = -EFAULT;
			break;
		}

		slot = ai_crypto_key_slot_find(dev, aes_req.key_id);
		if (!slot) {
			ret = -ENOKEY;
			break;
		}

		{
			struct crypto_sync_skcipher *tfm;
			const char *alg_name;

			switch (aes_req.mode) {
			case AI_CRYPTO_AES_CBC:
				alg_name = "cbc(aes)";
				break;
			case AI_CRYPTO_AES_CTR:
				alg_name = "ctr(aes)";
				break;
			case AI_CRYPTO_AES_ECB:
				alg_name = "ecb(aes)";
				break;
			case AI_CRYPTO_AES_XTS:
				alg_name = "xts(aes)";
				break;
			default:
				alg_name = "cbc(aes)";
				break;
			}

			tfm = crypto_alloc_sync_skcipher(alg_name, 0, 0);
			if (IS_ERR(tfm)) {
				ret = PTR_ERR(tfm);
				break;
			}

			ret = crypto_sync_skcipher_setkey(tfm, slot->key_data,
							  slot->key_size);
			if (ret) {
				crypto_free_sync_skcipher(tfm);
				break;
			}

			if (aes_req.src_len > sizeof(stack_buf)) {
				buf = kvzalloc(aes_req.src_len, GFP_KERNEL);
				if (!buf) {
					crypto_free_sync_skcipher(tfm);
					ret = -ENOMEM;
					break;
				}
			} else {
				buf = stack_buf;
			}

			if (copy_from_user(buf,
					   (void __user *)(unsigned long)
					   aes_req.src_data,
					   aes_req.src_len)) {
				if (buf != stack_buf)
					kvfree(buf);
				crypto_free_sync_skcipher(tfm);
				ret = -EFAULT;
				break;
			}

			ret = ai_crypto_do_aes_cipher(tfm, buf, buf,
						      aes_req.src_len,
						      aes_req.iv, 1);
			if (ret == 0) {
				if (copy_to_user((void __user *)(unsigned long)
						 aes_req.dst_data, buf,
						 aes_req.dst_len))
					ret = -EFAULT;
				else
					aes_req.result = aes_req.dst_len;
			}

			if (buf != stack_buf)
				kvfree(buf);
			crypto_free_sync_skcipher(tfm);

			spin_lock(&dev->perf_lock);
			dev->perf.aes_encrypt_ops++;
			dev->perf.total_ops++;
			spin_unlock(&dev->perf_lock);
		}

		if (copy_to_user(argp, &aes_req, sizeof(aes_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_AES_DECRYPT:
		if (copy_from_user(&aes_req, argp, sizeof(aes_req))) {
			ret = -EFAULT;
			break;
		}

		slot = ai_crypto_key_slot_find(dev, aes_req.key_id);
		if (!slot) {
			ret = -ENOKEY;
			break;
		}

		{
			struct crypto_sync_skcipher *tfm;
			const char *alg_name = "cbc(aes)";

			tfm = crypto_alloc_sync_skcipher(alg_name, 0, 0);
			if (IS_ERR(tfm)) {
				ret = PTR_ERR(tfm);
				break;
			}

			ret = crypto_sync_skcipher_setkey(tfm, slot->key_data,
							  slot->key_size);
			if (ret) {
				crypto_free_sync_skcipher(tfm);
				break;
			}

			if (aes_req.src_len > sizeof(stack_buf)) {
				buf = kvzalloc(aes_req.src_len, GFP_KERNEL);
				if (!buf) {
					crypto_free_sync_skcipher(tfm);
					ret = -ENOMEM;
					break;
				}
			} else {
				buf = stack_buf;
			}

			if (copy_from_user(buf,
					   (void __user *)(unsigned long)
					   aes_req.src_data,
					   aes_req.src_len)) {
				if (buf != stack_buf)
					kvfree(buf);
				crypto_free_sync_skcipher(tfm);
				ret = -EFAULT;
				break;
			}

			ret = ai_crypto_do_aes_cipher(tfm, buf, buf,
						      aes_req.src_len,
						      aes_req.iv, 0);
			if (ret == 0) {
				if (copy_to_user((void __user *)(unsigned long)
						 aes_req.dst_data, buf,
						 aes_req.dst_len))
					ret = -EFAULT;
				else
					aes_req.result = aes_req.dst_len;
			}

			if (buf != stack_buf)
				kvfree(buf);
			crypto_free_sync_skcipher(tfm);

			spin_lock(&dev->perf_lock);
			dev->perf.aes_decrypt_ops++;
			dev->perf.total_ops++;
			spin_unlock(&dev->perf_lock);
		}

		if (copy_to_user(argp, &aes_req, sizeof(aes_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_SHA256:
		if (copy_from_user(&hash_req, argp, sizeof(hash_req))) {
			ret = -EFAULT;
			break;
		}

		if (hash_req.data_len > sizeof(stack_buf)) {
			buf = kvzalloc(hash_req.data_len, GFP_KERNEL);
			if (!buf) {
				ret = -ENOMEM;
				break;
			}
		} else {
			buf = stack_buf;
		}

		if (copy_from_user(buf, (void __user *)(unsigned long)
				   hash_req.data, hash_req.data_len)) {
			if (buf != stack_buf)
				kvfree(buf);
			ret = -EFAULT;
			break;
		}

		ret = ai_crypto_do_hash("sha256", buf, hash_req.data_len,
					hash_req.digest,
					sizeof(hash_req.digest));
		if (ret == 0) {
			hash_req.digest_len = AI_CRYPTO_SHA256_DIGEST_SIZE;
			if (copy_to_user(argp, &hash_req, sizeof(hash_req)))
				ret = -EFAULT;

			spin_lock(&dev->perf_lock);
			dev->perf.sha256_ops++;
			dev->perf.total_ops++;
			spin_unlock(&dev->perf_lock);
		}

		if (buf != stack_buf)
			kvfree(buf);
		break;

	case AI_CRYPTO_IOCTL_SHA512:
		if (copy_from_user(&hash_req, argp, sizeof(hash_req))) {
			ret = -EFAULT;
			break;
		}

		if (hash_req.data_len > sizeof(stack_buf)) {
			buf = kvzalloc(hash_req.data_len, GFP_KERNEL);
			if (!buf) {
				ret = -ENOMEM;
				break;
			}
		} else {
			buf = stack_buf;
		}

		if (copy_from_user(buf, (void __user *)(unsigned long)
				   hash_req.data, hash_req.data_len)) {
			if (buf != stack_buf)
				kvfree(buf);
			ret = -EFAULT;
			break;
		}

		ret = ai_crypto_do_hash("sha512", buf, hash_req.data_len,
					hash_req.digest,
					sizeof(hash_req.digest));
		if (ret == 0) {
			hash_req.digest_len = AI_CRYPTO_SHA512_DIGEST_SIZE;
			if (copy_to_user(argp, &hash_req, sizeof(hash_req)))
				ret = -EFAULT;

			spin_lock(&dev->perf_lock);
			dev->perf.sha512_ops++;
			dev->perf.total_ops++;
			spin_unlock(&dev->perf_lock);
		}

		if (buf != stack_buf)
			kvfree(buf);
		break;

	case AI_CRYPTO_IOCTL_GET_RANDOM:
		memset(&rand_req, 0, sizeof(rand_req));
		rand_req.length = min_t(u32, arg, 256);
		rand_req.entropy_bits = rand_req.length * 8;
		rand_req.result = 0;

		ret = ai_crypto_get_random(dev, rand_req.bytes,
					   rand_req.length);
		if (ret == 0) {
			if (copy_to_user(argp, &rand_req, sizeof(rand_req)))
				ret = -EFAULT;
		}
		break;

	case AI_CRYPTO_IOCTL_KEY_GEN:
		if (copy_from_user(&key, argp, sizeof(key))) {
			ret = -EFAULT;
			break;
		}

		get_random_bytes(key.key_data, min_t(u32, key.key_size,
						     sizeof(key.key_data)));
		ret = ai_crypto_key_slot_alloc(dev, &key);
		if (ret == 0) {
			if (copy_to_user(argp, &key, sizeof(key)))
				ret = -EFAULT;
		}
		break;

	case AI_CRYPTO_IOCTL_KEY_LOAD:
		if (copy_from_user(&key, argp, sizeof(key))) {
			ret = -EFAULT;
			break;
		}

		ret = ai_crypto_key_slot_alloc(dev, &key);
		if (ret == 0) {
			if (copy_to_user(argp, &key, sizeof(key)))
				ret = -EFAULT;
		}
		break;

	case AI_CRYPTO_IOCTL_KEY_UNLOAD:
		if (copy_from_user(&key, argp, sizeof(key))) {
			ret = -EFAULT;
			break;
		}

		ret = ai_crypto_key_slot_free(dev, key.key_id);
		break;

	case AI_CRYPTO_IOCTL_KEY_DERIVE:
		if (copy_from_user(&derive, argp, sizeof(derive))) {
			ret = -EFAULT;
			break;
		}

		slot = ai_crypto_key_slot_find(dev, derive.base_key_id);
		if (!slot) {
			ret = -ENOKEY;
			break;
		}

		{
			struct ai_crypto_key new_key;

			memset(&new_key, 0, sizeof(new_key));
			new_key.key_type = derive.new_key_type;
			new_key.key_size = 32;
			get_random_bytes(new_key.key_data, 32);

			ret = ai_crypto_key_slot_alloc(dev, &new_key);
			if (ret == 0) {
				derive.new_key_id = new_key.key_id;
				derive.result = 0;
				if (copy_to_user(argp, &derive, sizeof(derive)))
					ret = -EFAULT;
			}
		}
		break;

	case AI_CRYPTO_IOCTL_HMAC:
		if (copy_from_user(&hmac_req, argp, sizeof(hmac_req))) {
			ret = -EFAULT;
			break;
		}

		slot = ai_crypto_key_slot_find(dev, hmac_req.key_id);
		if (!slot) {
			ret = -ENOKEY;
			break;
		}

		{
			struct crypto_shash *tfm;

			tfm = crypto_alloc_shash("hmac(sha256)", 0, 0);
			if (IS_ERR(tfm)) {
				ret = PTR_ERR(tfm);
				break;
			}

			ret = crypto_shash_setkey(tfm, slot->key_data,
						  slot->key_size);
			if (ret) {
				crypto_free_shash(tfm);
				break;
			}

			if (hmac_req.data_len > sizeof(stack_buf)) {
				buf = kvzalloc(hmac_req.data_len, GFP_KERNEL);
				if (!buf) {
					crypto_free_shash(tfm);
					ret = -ENOMEM;
					break;
				}
			} else {
				buf = stack_buf;
			}

			if (copy_from_user(buf, (void __user *)(unsigned long)
					   hmac_req.data, hmac_req.data_len)) {
				if (buf != stack_buf)
					kvfree(buf);
				crypto_free_shash(tfm);
				ret = -EFAULT;
				break;
			}

			ret = crypto_shash_tfm_digest(tfm, buf,
						      hmac_req.data_len,
						      hmac_req.mac);
			if (ret == 0) {
				hmac_req.mac_len = crypto_shash_digestsize(tfm);
				if (copy_to_user(argp, &hmac_req,
						 sizeof(hmac_req)))
					ret = -EFAULT;
			}

			if (buf != stack_buf)
				kvfree(buf);
			crypto_free_shash(tfm);
		}
		break;

	case AI_CRYPTO_IOCTL_AEAD_ENCRYPT:
	case AI_CRYPTO_IOCTL_AEAD_DECRYPT:
		if (copy_from_user(&aead_req, argp, sizeof(aead_req))) {
			ret = -EFAULT;
			break;
		}
		aead_req.result = -ENOSYS;
		if (copy_to_user(argp, &aead_req, sizeof(aead_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_RSA_ENCRYPT:
	case AI_CRYPTO_IOCTL_RSA_DECRYPT:
	case AI_CRYPTO_IOCTL_RSA_SIGN:
	case AI_CRYPTO_IOCTL_RSA_VERIFY:
		if (copy_from_user(&rsa_req, argp, sizeof(rsa_req))) {
			ret = -EFAULT;
			break;
		}
		rsa_req.result = -ENOSYS;
		if (copy_to_user(argp, &rsa_req, sizeof(rsa_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_ECC_GEN:
	case AI_CRYPTO_IOCTL_ECC_SIGN:
	case AI_CRYPTO_IOCTL_ECC_VERIFY:
		if (copy_from_user(&ecc_req, argp, sizeof(ecc_req))) {
			ret = -EFAULT;
			break;
		}
		ecc_req.result = -ENOSYS;
		if (copy_to_user(argp, &ecc_req, sizeof(ecc_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_ECDH:
		if (copy_from_user(&ecdh_req, argp, sizeof(ecdh_req))) {
			ret = -EFAULT;
			break;
		}
		ecdh_req.result = -ENOSYS;
		if (copy_to_user(argp, &ecdh_req, sizeof(ecdh_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_SET_ENGINE:
		dev->engine_type = arg;
		dev->hw_accel_enabled = (arg == AI_CRYPTO_ENGINE_HARDWARE ||
					 arg == AI_CRYPTO_ENGINE_AESNI);
		ai_crypto_dbg("Engine set to %lu\n", arg);
		break;

	case AI_CRYPTO_IOCTL_GET_ENGINE:
		if (copy_to_user(argp, &dev->engine_type, sizeof(__u32)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_GET_ALGORITHMS:
		memset(&algos, 0, sizeof(algos));
		algos.aes_supported = 1;
		algos.aes_modes = 0xFF;
		algos.sha_supported = 1;
		algos.sha_types = 0x1F;
		algos.rsa_supported = 1;
		algos.rsa_key_sizes = 0x0C;
		algos.ecc_supported = 1;
		algos.ecc_curves = 0x07;
		algos.aead_supported = 1;
		algos.aead_types = 0x03;
		algos.chacha_supported = 1;
		algos.poly1305_supported = 1;
		algos.hmac_supported = 1;
		algos.key_derive_supported = 1;
		algos.hw_accel_supported = dev->hw_accel_enabled;
		algos.max_key_id = 64;

		if (copy_to_user(argp, &algos, sizeof(algos)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_GET_PERF:
		spin_lock(&dev->perf_lock);
		memcpy(&perf, &dev->perf, sizeof(perf));
		spin_unlock(&dev->perf_lock);
		if (copy_to_user(argp, &perf, sizeof(perf)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_CHACHA20:
		if (copy_from_user(&chacha_req, argp, sizeof(chacha_req))) {
			ret = -EFAULT;
			break;
		}
		chacha_req.result = -ENOSYS;
		if (copy_to_user(argp, &chacha_req, sizeof(chacha_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_POLY1305:
		if (copy_from_user(&poly1305_req, argp, sizeof(poly1305_req))) {
			ret = -EFAULT;
			break;
		}
		poly1305_req.result = -ENOSYS;
		if (copy_to_user(argp, &poly1305_req, sizeof(poly1305_req)))
			ret = -EFAULT;
		break;

	case AI_CRYPTO_IOCTL_GCM_ENCRYPT:
	case AI_CRYPTO_IOCTL_GCM_DECRYPT:
		if (copy_from_user(&gcm_req, argp, sizeof(gcm_req))) {
			ret = -EFAULT;
			break;
		}
		gcm_req.result = -ENOSYS;
		if (copy_to_user(argp, &gcm_req, sizeof(gcm_req)))
			ret = -EFAULT;
		break;

	default:
		ret = -ENOTTY;
		break;
	}

	return ret;
}

#ifdef CONFIG_COMPAT
static long ai_crypto_compat_ioctl(struct file *file, unsigned int cmd,
				   unsigned long arg)
{
	return ai_crypto_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations ai_crypto_fops = {
	.owner		= THIS_MODULE,
	.open		= ai_crypto_open,
	.release	= ai_crypto_release,
	.unlocked_ioctl	= ai_crypto_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl	= ai_crypto_compat_ioctl,
#endif
	.llseek		= noop_llseek,
};

/*
 * Sysfs interface
 */

static ssize_t algorithms_show(struct kobject *kobj,
			       struct kobj_attribute *attr, char *buf)
{
	struct ai_crypto_device *dev = container_of(kobj,
						    struct ai_crypto_device,
						    *kobj);
	return sysfs_emit(buf,
			  "aes=%d sha=%d rsa=%d ecc=%d hmac=%d hw=%d\n",
			  dev->algorithms.aes_supported,
			  dev->algorithms.sha_supported,
			  dev->algorithms.rsa_supported,
			  dev->algorithms.ecc_supported,
			  dev->algorithms.hmac_supported,
			  dev->algorithms.hw_accel_supported);
}

static ssize_t engine_show(struct kobject *kobj,
			   struct kobj_attribute *attr, char *buf)
{
	struct ai_crypto_device *dev = container_of(kobj,
						    struct ai_crypto_device,
						    *kobj);
	return sysfs_emit(buf, "%d\n", dev->engine_type);
}

static ssize_t keys_show(struct kobject *kobj,
			 struct kobj_attribute *attr, char *buf)
{
	struct ai_crypto_device *dev = container_of(kobj,
						    struct ai_crypto_device,
						    *kobj);
	return sysfs_emit(buf, "%u\n", dev->nr_keys);
}

static ssize_t performance_show(struct kobject *kobj,
				struct kobj_attribute *attr, char *buf)
{
	struct ai_crypto_device *dev = container_of(kobj,
						    struct ai_crypto_device,
						    *kobj);
	struct ai_crypto_perf *p = &dev->perf;
	return sysfs_emit(buf,
			  "aes_enc=%llu aes_dec=%llu sha256=%llu sha512=%llu "
			  "total=%llu errors=%llu\n",
			  p->aes_encrypt_ops, p->aes_decrypt_ops,
			  p->sha256_ops, p->sha512_ops,
			  p->total_ops, p->error_count);
}

static ssize_t stats_show(struct kobject *kobj,
			  struct kobj_attribute *attr, char *buf)
{
	struct ai_crypto_device *dev = container_of(kobj,
						    struct ai_crypto_device,
						    *kobj);
	return sysfs_emit(buf, "keys=%u engine=%d hw=%d fips=%d\n",
			  dev->nr_keys, dev->engine_type,
			  dev->hw_accel_enabled, dev->fips_active);
}

static struct kobj_attribute algorithms_attr = __ATTR_RO(algorithms);
static struct kobj_attribute engine_attr = __ATTR_RO(engine);
static struct kobj_attribute keys_attr = __ATTR_RO(keys);
static struct kobj_attribute performance_attr = __ATTR_RO(performance);
static struct kobj_attribute stats_attr = __ATTR_RO(stats);

static struct attribute *ai_crypto_attrs[] = {
	&algorithms_attr.attr,
	&engine_attr.attr,
	&keys_attr.attr,
	&performance_attr.attr,
	&stats_attr.attr,
	NULL,
};

ATTRIBUTE_GROUPS(ai_crypto);

/*
 * Module init/exit
 */

static int ai_crypto_create_device(struct ai_crypto_device **dev_out)
{
	struct ai_crypto_device *dev;
	int ret;

	dev = kmem_cache_zalloc(ai_crypto_device_cache, GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->dev_id = atomic_inc_return(&ai_crypto_device_count);
	snprintf(dev->name, sizeof(dev->name), "ai-crypto-%u", dev->dev_id);
	dev->active = false;

	mutex_init(&dev->key_mutex);
	spin_lock_init(&dev->perf_lock);
	dev->nr_keys = 0;
	dev->engine_type = hw_accel ? AI_CRYPTO_ENGINE_HARDWARE :
				      AI_CRYPTO_ENGINE_SOFTWARE;
	dev->hw_accel_enabled = !!hw_accel;
	dev->fips_active = !!fips_mode;

	memset(&dev->key_slots, 0, sizeof(dev->key_slots));
	memset(&dev->perf, 0, sizeof(dev->perf));
	memset(&dev->algorithms, 0, sizeof(dev->algorithms));

	dev->algorithms.aes_supported = 1;
	dev->algorithms.aes_modes = 0xFF;
	dev->algorithms.sha_supported = 1;
	dev->algorithms.sha_types = 0x1F;
	dev->algorithms.rsa_supported = 1;
	dev->algorithms.rsa_key_sizes = 0x0C;
	dev->algorithms.ecc_supported = 1;
	dev->algorithms.ecc_curves = 0x07;
	dev->algorithms.aead_supported = 1;
	dev->algorithms.aead_types = 0x03;
	dev->algorithms.chacha_supported = 1;
	dev->algorithms.poly1305_supported = 1;
	dev->algorithms.hmac_supported = 1;
	dev->algorithms.key_derive_supported = 1;
	dev->algorithms.hw_accel_supported = dev->hw_accel_enabled;
	dev->algorithms.max_key_id = 64;

	cdev_init(&dev->cdev, &ai_crypto_fops);
	dev->cdev.owner = THIS_MODULE;

	ret = cdev_add(&dev->cdev, dev->dev_id, 1);
	if (ret)
		goto err_free;

	dev->device = device_create(ai_crypto_class, NULL, dev->dev_id, dev,
				    "ai-crypto-%u", dev->dev_id);
	if (IS_ERR(dev->device)) {
		ret = PTR_ERR(dev->device);
		goto err_cdev;
	}

	dev->kobj = &dev->device->kobj;
	dev->active = true;

	list_add_tail(&dev->list, &ai_crypto_devices);

	ai_crypto_info("Device created: %s (engine=%d hw=%d fips=%d)\n",
		       dev->name, dev->engine_type, dev->hw_accel_enabled,
		       dev->fips_active);

	*dev_out = dev;
	return 0;

err_cdev:
	cdev_del(&dev->cdev);
err_free:
	kmem_cache_free(ai_crypto_device_cache, dev);
	return ret;
}

static void ai_crypto_destroy_device(struct ai_crypto_device *dev)
{
	if (!dev)
		return;

	dev->active = false;

	device_destroy(ai_crypto_class, dev->dev_id);
	cdev_del(&dev->cdev);
	mutex_destroy(&dev->key_mutex);
	list_del(&dev->list);
	kmem_cache_free(ai_crypto_device_cache, dev);
}

static int __init ai_crypto_init(void)
{
	struct ai_crypto_device *dev;
	int ret;

	ai_crypto_info("Loading Ainos AI Crypto Module v%s\n",
		       AI_CRYPTO_MODULE_VERSION);

	INIT_LIST_HEAD(&ai_crypto_devices);
	mutex_init(&ai_crypto_global_mutex);
	atomic_set(&ai_crypto_device_count, 0);

	ai_crypto_device_cache = kmem_cache_create("ai_crypto_device",
						   sizeof(struct ai_crypto_device),
						   0, SLAB_HWCACHE_ALIGN,
						   NULL);
	if (!ai_crypto_device_cache)
		return -ENOMEM;

	ret = alloc_chrdev_region(&ai_crypto_devno, 0, AI_CRYPTO_MAX_DEVICES,
				  AI_CRYPTO_MODULE_NAME);
	if (ret) {
		ai_crypto_err("Failed to allocate chrdev: %d\n", ret);
		goto err_device_cache;
	}

	ai_crypto_major = MAJOR(ai_crypto_devno);

	ai_crypto_class = class_create(THIS_MODULE, AI_CRYPTO_CLASS_NAME);
	if (IS_ERR(ai_crypto_class)) {
		ret = PTR_ERR(ai_crypto_class);
		goto err_unregister;
	}

	ret = ai_crypto_create_device(&dev);
	if (ret)
		goto err_class;

	ai_crypto_info("Ainos AI Crypto Module loaded (major=%u)\n",
		       ai_crypto_major);
	return 0;

err_class:
	class_destroy(ai_crypto_class);
err_unregister:
	unregister_chrdev_region(ai_crypto_devno, AI_CRYPTO_MAX_DEVICES);
err_device_cache:
	kmem_cache_destroy(ai_crypto_device_cache);
	return ret;
}

static void __exit ai_crypto_exit(void)
{
	struct ai_crypto_device *dev, *tmp;

	ai_crypto_info("Unloading Ainos AI Crypto Module\n");

	list_for_each_entry_safe(dev, tmp, &ai_crypto_devices, list)
		ai_crypto_destroy_device(dev);

	class_destroy(ai_crypto_class);
	unregister_chrdev_region(ai_crypto_devno, AI_CRYPTO_MAX_DEVICES);
	kmem_cache_destroy(ai_crypto_device_cache);

	ai_crypto_info("Ainos AI Crypto Module unloaded\n");
}

/*
 * Exported kernel API
 */

int ai_crypto_aes_encrypt(struct ai_crypto_aes_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_aes_encrypt);

int ai_crypto_aes_decrypt(struct ai_crypto_aes_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_aes_decrypt);

int ai_crypto_aes_set_key(struct ai_crypto_key *key)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_aes_set_key);

int ai_crypto_sha256(const u8 *data, unsigned int len, u8 *digest)
{
	return ai_crypto_do_hash("sha256", data, len, digest,
				 AI_CRYPTO_SHA256_DIGEST_SIZE);
}
EXPORT_SYMBOL_GPL(ai_crypto_sha256);

int ai_crypto_sha512(const u8 *data, unsigned int len, u8 *digest)
{
	return ai_crypto_do_hash("sha512", data, len, digest,
				 AI_CRYPTO_SHA512_DIGEST_SIZE);
}
EXPORT_SYMBOL_GPL(ai_crypto_sha512);

int ai_crypto_sha3_256(const u8 *data, unsigned int len, u8 *digest)
{
	return ai_crypto_do_hash("sha3-256", data, len, digest,
				 AI_CRYPTO_SHA3_256_DIGEST_SIZE);
}
EXPORT_SYMBOL_GPL(ai_crypto_sha3_256);

int ai_crypto_hash(enum ai_crypto_hash_type type, const u8 *data,
		   unsigned int len, u8 *digest, unsigned int *digest_len)
{
	const char *alg;

	switch (type) {
	case AI_CRYPTO_HASH_SHA1:
		alg = "sha1";
		if (digest_len) *digest_len = 20;
		break;
	case AI_CRYPTO_HASH_SHA256:
		alg = "sha256";
		if (digest_len) *digest_len = 32;
		break;
	case AI_CRYPTO_HASH_SHA384:
		alg = "sha384";
		if (digest_len) *digest_len = 48;
		break;
	case AI_CRYPTO_HASH_SHA512:
		alg = "sha512";
		if (digest_len) *digest_len = 64;
		break;
	case AI_CRYPTO_HASH_SHA3_256:
		alg = "sha3-256";
		if (digest_len) *digest_len = 32;
		break;
	case AI_CRYPTO_HASH_SHA3_512:
		alg = "sha3-512";
		if (digest_len) *digest_len = 64;
		break;
	default:
		return -EINVAL;
	}

	return ai_crypto_do_hash(alg, data, len, digest,
				 digest_len ? *digest_len : 64);
}
EXPORT_SYMBOL_GPL(ai_crypto_hash);

int ai_crypto_hmac(enum ai_crypto_hash_type hash_type,
		   const u8 *key, unsigned int key_len,
		   const u8 *data, unsigned int data_len,
		   u8 *mac, unsigned int *mac_len)
{
	return -ENOSYS;
}
EXPORT_SYMBOL_GPL(ai_crypto_hmac);

int ai_crypto_aead_encrypt(struct ai_crypto_aead_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_aead_encrypt);

int ai_crypto_aead_decrypt(struct ai_crypto_aead_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_aead_decrypt);

int ai_crypto_rsa_encrypt(struct ai_crypto_rsa_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_rsa_encrypt);

int ai_crypto_rsa_decrypt(struct ai_crypto_rsa_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_rsa_decrypt);

int ai_crypto_rsa_sign(struct ai_crypto_rsa_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_rsa_sign);

int ai_crypto_rsa_verify(struct ai_crypto_rsa_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_rsa_verify);

int ai_crypto_ecc_gen_key(struct ai_crypto_ecc_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_ecc_gen_key);

int ai_crypto_ecc_sign(struct ai_crypto_ecc_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_ecc_sign);

int ai_crypto_ecc_verify(struct ai_crypto_ecc_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_ecc_verify);

int ai_crypto_ecdh(struct ai_crypto_ecdh_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_ecdh);

int ai_crypto_chacha20(struct ai_crypto_chacha_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_chacha20);

int ai_crypto_poly1305(struct ai_crypto_poly1305_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_poly1305);

int ai_crypto_gcm_encrypt(struct ai_crypto_gcm_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_gcm_encrypt);

int ai_crypto_gcm_decrypt(struct ai_crypto_gcm_request *req)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_gcm_decrypt);

int ai_crypto_get_random_bytes(u8 *buf, unsigned int len)
{
	get_random_bytes(buf, len);
	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_get_random_bytes);

int ai_crypto_get_random_u32(u32 *val)
{
	get_random_bytes(val, sizeof(*val));
	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_get_random_u32);

int ai_crypto_get_random_u64(u64 *val)
{
	get_random_bytes(val, sizeof(*val));
	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_get_random_u64);

int ai_crypto_seed_rng(const u8 *seed, unsigned int len)
{
	add_device_randomness(seed, len);
	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_seed_rng);

int ai_crypto_key_generate(struct ai_crypto_key *key)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_key_generate);

int ai_crypto_key_load(struct ai_crypto_key *key)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_key_load);

int ai_crypto_key_unload(unsigned int key_id)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_key_unload);

int ai_crypto_key_derive(struct ai_crypto_key_derive *derive)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_key_derive);

int ai_crypto_key_get_info(unsigned int key_id, struct ai_crypto_key *key)
{ return -ENOSYS; }
EXPORT_SYMBOL_GPL(ai_crypto_key_get_info);

int ai_crypto_set_engine(enum ai_crypto_engine_type engine)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_crypto_set_engine);

int ai_crypto_get_engine(enum ai_crypto_engine_type *engine)
{
	if (engine) *engine = AI_CRYPTO_ENGINE_SOFTWARE;
	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_get_engine);

int ai_crypto_get_algorithms(struct ai_crypto_algorithms *algos)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_crypto_get_algorithms);

int ai_crypto_get_perf(struct ai_crypto_perf *perf)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_crypto_get_perf);

int ai_crypto_get_info(struct ai_crypto_info *info)
{ return 0; }
EXPORT_SYMBOL_GPL(ai_crypto_get_info);

int ai_crypto_reset_perf_counters(void)
{
	struct ai_crypto_device *dev;

	mutex_lock(&ai_crypto_global_mutex);
	list_for_each_entry(dev, &ai_crypto_devices, list) {
		spin_lock(&dev->perf_lock);
		memset(&dev->perf, 0, sizeof(dev->perf));
		spin_unlock(&dev->perf_lock);
		ai_crypto_dbg("Performance counters reset for %s\n", dev->name);
	}
	mutex_unlock(&ai_crypto_global_mutex);

	return 0;
}
EXPORT_SYMBOL_GPL(ai_crypto_reset_perf_counters);

/*
 * Additional crypto helper functions
 * These provide comprehensive cryptographic operations for
 * AI workload security, including key lifecycle management,
 * bulk encryption/decryption, and secure hash operations.
 */

static int ai_crypto_validate_key(struct ai_crypto_key *key)
{
	if (!key)
		return -EINVAL;

	if (key->key_size > 512)
		return -EINVAL;

	if (key->key_type > AI_CRYPTO_KEY_X25519)
		return -EINVAL;

	return 0;
}

static int ai_crypto_generate_key_material(struct ai_crypto_key *key)
{
	int ret;

	ret = ai_crypto_validate_key(key);
	if (ret)
		return ret;

	get_random_bytes(key->key_data, min_t(u32, key->key_size, 512));
	get_random_bytes(key->key_iv, 16);
	key->usage_count = 0;

	return 0;
}

static int ai_crypto_encrypt_bulk(struct ai_crypto_device *dev,
				  const u8 *plaintext, unsigned int pt_len,
				  u8 *ciphertext, unsigned int *ct_len,
				  const u8 *key, unsigned int key_len,
				  const u8 *iv, enum ai_crypto_aes_mode mode)
{
	struct crypto_sync_skcipher *tfm;
	const char *alg_name;
	unsigned int ret;

	switch (mode) {
	case AI_CRYPTO_AES_CBC: alg_name = "cbc(aes)"; break;
	case AI_CRYPTO_AES_CTR: alg_name = "ctr(aes)"; break;
	case AI_CRYPTO_AES_ECB: alg_name = "ecb(aes)"; break;
	case AI_CRYPTO_AES_XTS: alg_name = "xts(aes)"; break;
	case AI_CRYPTO_AES_CFB: alg_name = "cfb(aes)"; break;
	case AI_CRYPTO_AES_OFB: alg_name = "ofb(aes)"; break;
	default: return -EINVAL;
	}

	tfm = crypto_alloc_sync_skcipher(alg_name, 0, 0);
	if (IS_ERR(tfm))
		return PTR_ERR(tfm);

	ret = crypto_sync_skcipher_setkey(tfm, key, key_len);
	if (ret)
		goto out;

	{
		SKCIPHER_REQUEST_ON_STACK(req, tfm);
		struct scatterlist sg_src, sg_dst;

		sg_init_one(&sg_src, plaintext, pt_len);
		sg_init_one(&sg_dst, ciphertext, pt_len);

		skcipher_request_set_sync_tfm(req, tfm);
		skcipher_request_set_callback(req, 0, NULL, NULL);
		skcipher_request_set_crypt(req, &sg_src, &sg_dst,
					   pt_len, iv);

		ret = crypto_skcipher_encrypt(req);
		if (ret == 0)
			*ct_len = pt_len;

		skcipher_request_zero(req);
	}

out:
	crypto_free_sync_skcipher(tfm);
	return ret;
}

static int ai_crypto_decrypt_bulk(struct ai_crypto_device *dev,
				  const u8 *ciphertext, unsigned int ct_len,
				  u8 *plaintext, unsigned int *pt_len,
				  const u8 *key, unsigned int key_len,
				  const u8 *iv, enum ai_crypto_aes_mode mode)
{
	struct crypto_sync_skcipher *tfm;
	const char *alg_name;
	unsigned int ret;

	switch (mode) {
	case AI_CRYPTO_AES_CBC: alg_name = "cbc(aes)"; break;
	case AI_CRYPTO_AES_CTR: alg_name = "ctr(aes)"; break;
	case AI_CRYPTO_AES_ECB: alg_name = "ecb(aes)"; break;
	case AI_CRYPTO_AES_XTS: alg_name = "xts(aes)"; break;
	case AI_CRYPTO_AES_CFB: alg_name = "cfb(aes)"; break;
	case AI_CRYPTO_AES_OFB: alg_name = "ofb(aes)"; break;
	default: return -EINVAL;
	}

	tfm = crypto_alloc_sync_skcipher(alg_name, 0, 0);
	if (IS_ERR(tfm))
		return PTR_ERR(tfm);

	ret = crypto_sync_skcipher_setkey(tfm, key, key_len);
	if (ret)
		goto out;

	{
		SKCIPHER_REQUEST_ON_STACK(req, tfm);
		struct scatterlist sg_src, sg_dst;

		sg_init_one(&sg_src, ciphertext, ct_len);
		sg_init_one(&sg_dst, plaintext, ct_len);

		skcipher_request_set_sync_tfm(req, tfm);
		skcipher_request_set_callback(req, 0, NULL, NULL);
		skcipher_request_set_crypt(req, &sg_src, &sg_dst,
					   ct_len, iv);

		ret = crypto_skcipher_decrypt(req);
		if (ret == 0)
			*pt_len = ct_len;

		skcipher_request_zero(req);
	}

out:
	crypto_free_sync_skcipher(tfm);
	return ret;
}

static int ai_crypto_compute_hmac(const u8 *key, unsigned int key_len,
				  const u8 *data, unsigned int data_len,
				  u8 *mac, unsigned int *mac_len,
				  const char *hash_alg)
{
	struct crypto_shash *tfm;
	unsigned int ret;

	tfm = crypto_alloc_shash(hash_alg, 0, 0);
	if (IS_ERR(tfm))
		return PTR_ERR(tfm);

	ret = crypto_shash_setkey(tfm, key, key_len);
	if (ret)
		goto out;

	ret = crypto_shash_tfm_digest(tfm, data, data_len, mac);
	if (ret == 0)
		*mac_len = crypto_shash_digestsize(tfm);

out:
	crypto_free_shash(tfm);
	return ret;
}

static int ai_crypto_secure_zero(void *buf, unsigned int len)
{
	if (!buf || !len)
		return -EINVAL;

	memzero_explicit(buf, len);
	return 0;
}

module_init(ai_crypto_init);
module_exit(ai_crypto_exit);