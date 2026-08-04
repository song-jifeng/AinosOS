// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI Vector Acceleration sysfs interface
 * =================================================
 * Exposes CPU feature detection and benchmark results
 * via /sys/module/ai-vector-accel/parameters/
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/sysfs.h>
#include <linux/stat.h>
#include <linux/device.h>
#include <linux/string.h>

#include "arch/x86/simd_impl.h"

/* Buffer for feature string */
static char feature_buf[256];

/* ============================================
 * Sysfs show functions
 * ============================================ */

/* Show current accelerator name */
static ssize_t accel_name_show(struct kobject *kobj,
                                struct kobj_attribute *attr, char *buf)
{
    return snprintf(buf, PAGE_SIZE, "%s\n", ai_vector_get_name());
}

/* Show vector register width */
static ssize_t vector_width_show(struct kobject *kobj,
                                  struct kobj_attribute *attr, char *buf)
{
    return snprintf(buf, PAGE_SIZE, "%d\n", ai_vector_get_vector_size());
}

/* Show available x86 features */
static ssize_t features_show(struct kobject *kobj,
                              struct kobj_attribute *attr, char *buf)
{
    int off = 0;

#ifdef CONFIG_X86
    off += snprintf(buf + off, PAGE_SIZE - off,
        "avx2=%d\n"
        "avx512=%d\n"
        "avx512_vnni=%d\n"
        "amx=%d\n"
        "amx_bf16=%d\n"
        "f16c=%d\n"
        "ssse3=%d\n",
        ai_vector_has_feature("avx2"),
        ai_vector_has_feature("avx512"),
        ai_vector_has_feature("avx512_vnni"),
        ai_vector_has_feature("amx"),
        ai_vector_has_feature("amx_bf16"),
        ai_vector_has_feature("f16c"),
        ai_vector_has_feature("ssse3"));
#elif defined(CONFIG_ARM64)
    off += snprintf(buf + off, PAGE_SIZE - off,
        "neon=%d\n"
        "sve=%d\n"
        "sve2=%d\n"
        "i8mm=%d\n",
        ai_vector_has_feature("neon"),
        ai_vector_has_feature("sve"),
        ai_vector_has_feature("sve2"),
        ai_vector_has_feature("i8mm"));
#endif

    return off;
}

/* ============================================
 * Sysfs attributes
 * ============================================ */
static struct kobj_attribute accel_name_attr =
    __ATTR(accel_name, 0444, accel_name_show, NULL);
static struct kobj_attribute vector_width_attr =
    __ATTR(vector_width, 0444, vector_width_show, NULL);
static struct kobj_attribute features_attr =
    __ATTR(features, 0444, features_show, NULL);

static struct attribute *accel_attrs[] = {
    &accel_name_attr.attr,
    &vector_width_attr.attr,
    &features_attr.attr,
    NULL,
};

static struct attribute_group accel_attr_group = {
    .attrs = accel_attrs,
};

/* ============================================
 * Initialization
 * ============================================ */
int ai_vector_sysfs_init(struct kobject *parent)
{
    return sysfs_create_group(parent, &accel_attr_group);
}

void ai_vector_sysfs_exit(struct kobject *parent)
{
    sysfs_remove_group(parent, &accel_attr_group);
}

EXPORT_SYMBOL_GPL(ai_vector_sysfs_init);
EXPORT_SYMBOL_GPL(ai_vector_sysfs_exit);