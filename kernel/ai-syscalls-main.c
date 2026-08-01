// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 系统调用注册模块
 * ==========================================
 * 注册 AI 相关的系统调用和设备接口
 *
 * 注册系统调用:
 * - sys_ai_inference:      AI 推理请求
 * - sys_ai_embedding:      文本嵌入
 * - sys_ai_semantic_search: 语义搜索
 * - sys_ai_model_load:      加载模型
 * - sys_ai_model_unload:    卸载模型
 * - sys_ai_context_store:   存储上下文
 * - sys_ai_context_retrieve: 检索上下文
 * - sys_ai_status:          获取系统状态
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/syscalls.h>
#include <linux/uaccess.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/slab.h>
#include <linux/ioctl.h>
#include <linux/string.h>

#include "ainos/ai-abi.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI System Calls");
MODULE_VERSION("0.1.0");

/* 引用 AI 调度器 */
extern int ai_sched_submit(struct ai_inference_req *req,
                            struct ai_inference_resp *resp);
extern int ai_sched_submit_async(struct ai_inference_req *req,
                                  uint64_t *task_id);
extern int ai_sched_cancel(uint64_t task_id);
extern void ai_sched_get_status(struct ai_system_status *status);

/* ============================================
 * AI 设备文件 (/dev/ainos)
 * ============================================ */

static int ainos_device_open(struct inode *inode, struct file *file)
{
    return 0;
}

static int ainos_device_release(struct inode *inode, struct file *file)
{
    return 0;
}

static long ainos_device_ioctl(struct file *file, unsigned int cmd,
                                unsigned long arg)
{
    void __user *argp = (void __user *)arg;
    struct ai_system_status status;
    uint64_t val;
    int ret = 0;

    switch (cmd) {
    case AI_IOCTL_GET_STATUS:
        ai_sched_get_status(&status);
        if (copy_to_user(argp, &status, sizeof(status)))
            ret = -EFAULT;
        break;

    case AI_IOCTL_CANCEL_TASK:
        if (copy_from_user(&val, argp, sizeof(val))) {
            ret = -EFAULT;
            break;
        }
        ret = ai_sched_cancel(val);
        break;

    default:
        ret = -ENOTTY;
        break;
    }

    return ret;
}

static const struct file_operations ainos_fops = {
    .owner          = THIS_MODULE,
    .open           = ainos_device_open,
    .release        = ainos_device_release,
    .unlocked_ioctl = ainos_device_ioctl,
};

static struct miscdevice ainos_device = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = "ainos",
    .fops  = &ainos_fops,
};

/* ============================================
 * 系统调用实现
 * ============================================ */

/* AI 推理请求 */
SYSCALL_DEFINE2(ai_inference,
                struct ai_inference_req __user *, req_u,
                struct ai_inference_resp __user *, resp_u)
{
    struct ai_inference_req req;
    struct ai_inference_resp resp;
    int ret;

    if (!req_u || !resp_u)
        return -AI_ERR_INVALID_PARAM;

    /* 从用户空间复制请求 */
    if (copy_from_user(&req, req_u, sizeof(req)))
        return -EFAULT;

    /* 提交到调度器 */
    memset(&resp, 0, sizeof(resp));
    ret = ai_sched_submit(&req, &resp);

    /* 复制响应到用户空间 */
    if (copy_to_user(resp_u, &resp, sizeof(resp)))
        return -EFAULT;

    return ret;
}

/* 获取文本嵌入向量 */
SYSCALL_DEFINE3(ai_embedding,
                const char __user *, text,
                size_t, len,
                float __user *, vector)
{
    /* TODO: 实现嵌入向量生成 */
    pr_debug("ainos: ai_embedding called (len=%zu)\n", len);
    return -AI_ERR_NOT_SUPPORTED;
}

/* 语义搜索 */
SYSCALL_DEFINE3(ai_semantic_search,
                const char __user *, query,
                struct ai_search_result __user *, results,
                size_t, max_results)
{
    /* TODO: 实现语义搜索 */
    pr_debug("ainos: ai_semantic_search called (max=%zu)\n", max_results);
    return -AI_ERR_NOT_SUPPORTED;
}

/* 加载模型 */
SYSCALL_DEFINE2(ai_model_load,
                const char __user *, path,
                uint64_t __user *, model_id)
{
    /* TODO: 实现模型加载 */
    pr_debug("ainos: ai_model_load called\n");
    return -AI_ERR_NOT_SUPPORTED;
}

/* 卸载模型 */
SYSCALL_DEFINE1(ai_model_unload, uint64_t, model_id)
{
    /* TODO: 实现模型卸载 */
    pr_debug("ainos: ai_model_unload called (id=%llu)\n", model_id);
    return -AI_ERR_NOT_SUPPORTED;
}

/* 存储上下文 */
SYSCALL_DEFINE5(ai_context_store,
                uint64_t, session_id,
                const char __user *, key,
                size_t, key_len,
                const char __user *, value,
                size_t, value_len)
{
    /* TODO: 实现上下文存储 */
    pr_debug("ainos: ai_context_store called (session=%llu)\n", session_id);
    return -AI_ERR_NOT_SUPPORTED;
}

/* 检索上下文 */
SYSCALL_DEFINE3(ai_context_retrieve,
                uint64_t, session_id,
                const char __user *, key,
                char __user *, value)
{
    /* TODO: 实现上下文检索 */
    pr_debug("ainos: ai_context_retrieve called (session=%llu)\n", session_id);
    return -AI_ERR_NOT_SUPPORTED;
}

/* 获取系统状态 */
SYSCALL_DEFINE1(ai_status, struct ai_system_status __user *, status)
{
    struct ai_system_status st;

    if (!status)
        return -AI_ERR_INVALID_PARAM;

    ai_sched_get_status(&st);

    if (copy_to_user(status, &st, sizeof(st)))
        return -EFAULT;

    return 0;
}

/* ============================================
 * 模块初始化/退出
 * ============================================ */

static int __init ai_syscalls_init(void)
{
    int ret;

    pr_info("ainos: AI Syscalls loading...\n");

    /* 注册设备 */
    ret = misc_register(&ainos_device);
    if (ret) {
        pr_err("ainos: failed to register device: %d\n", ret);
        return ret;
    }

    pr_info("ainos: AI Syscalls loaded. Device: /dev/ainos\n");
    return 0;
}

static void __exit ai_syscalls_exit(void)
{
    misc_deregister(&ainos_device);
    pr_info("ainos: AI Syscalls unloaded\n");
}

module_init(ai_syscalls_init);
module_exit(ai_syscalls_exit);