// Ainos OS - /proc/ai 虚拟 AI 文件系统
// 通过 VFS 接口暴露 AI 能力，支持 read/write 操作
//
// 使用:
//   cat /proc/ai/status          -> 系统状态
//   echo "你好" > /proc/ai/infer  -> 推理请求
//   cat /proc/ai/infer           -> 读取上次结果

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/sched.h>
#include <linux/version.h>

#define PROC_AI_DIR "ai"
#define BUF_SIZE 4096

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("/proc/ai - AI virtual filesystem interface");
MODULE_VERSION("0.1.0");

static struct proc_dir_entry *ai_dir;
static struct proc_dir_entry *ai_infer;
static struct proc_dir_entry *ai_status;
static struct proc_dir_entry *ai_models;
static struct proc_dir_entry *ai_embed;
static struct proc_dir_entry *ai_config;

/* 共享缓冲区用于存储推理结果 */
static char *ai_output_buf;
static size_t ai_output_len;

/* 推理请求输入 */
static char *ai_input_buf;
static size_t ai_input_len;

/* /proc/ai/status 显示 */
static int status_show(struct seq_file *m, void *v) {
    seq_printf(m, "Ainos AI Status\n");
    seq_printf(m, "===============\n");
    seq_printf(m, "state: running\n");
    seq_printf(m, "uptime: %lu\n", get_seconds());
    seq_printf(m, "models_loaded: 0\n");
    seq_printf(m, "inferences: %lu\n", 0UL);
    seq_printf(m, "backend: local\n");
    return 0;
}
static int status_open(struct inode *inode, struct file *file) {
    return single_open(file, status_show, NULL);
}

/* /proc/ai/status 写操作 - 更新配置 */
static ssize_t status_write(struct file *file, const char __user *buf,
                            size_t len, loff_t *off) {
    char cmd[64];
    if (len > sizeof(cmd) - 1) return -EINVAL;
    if (copy_from_user(cmd, buf, len)) return -EFAULT;
    cmd[len] = '\0';

    /* 去除换行符 */
    if (len > 0 && cmd[len-1] == '\n') cmd[len-1] = '\0';

    if (strcmp(cmd, "reload") == 0) {
        /* 重新加载配置 */
        pr_info("proc-ai: reloading configuration\n");
        return len;
    }
    if (strcmp(cmd, "reset") == 0) {
        /* 重置统计 */
        pr_info("proc-ai: resetting stats\n");
        return len;
    }
    return -EINVAL;
}

/* /proc/ai/infer 读操作 - 返回推理结果 */
static ssize_t infer_read(struct file *file, char __user *buf,
                          size_t len, loff_t *off) {
    if (*off > 0) return 0;
    if (!ai_output_buf || ai_output_len == 0) {
        const char *msg = "No inference result available.\n";
        size_t msg_len = strlen(msg);
        if (len < msg_len) return -EINVAL;
        if (copy_to_user(buf, msg, msg_len)) return -EFAULT;
        *off += msg_len;
        return msg_len;
    }
    if (len < ai_output_len) return -EINVAL;
    if (copy_to_user(buf, ai_output_buf, ai_output_len)) return -EFAULT;
    *off += ai_output_len;
    return ai_output_len;
}

/* /proc/ai/infer 写操作 - 提交推理请求 */
static ssize_t infer_write(struct file *file, const char __user *buf,
                           size_t len, loff_t *off) {
    char *input;

    if (len > BUF_SIZE - 1) return -EINVAL;
    input = kmalloc(len + 1, GFP_KERNEL);
    if (!input) return -ENOMEM;

    if (copy_from_user(input, buf, len)) {
        kfree(input);
        return -EFAULT;
    }
    input[len] = '\0';
    /* 去除换行符 */
    if (len > 0 && input[len-1] == '\n') input[len-1] = '\0';

    pr_info("proc-ai: inference request: %s\n", input);

    /* 模拟推理 - 实际应通过 IPC 发给 ai-daemon */
    if (ai_output_buf) kfree(ai_output_buf);
    ai_output_buf = kmalloc(BUF_SIZE, GFP_KERNEL);
    if (ai_output_buf) {
        ai_output_len = snprintf(ai_output_buf, BUF_SIZE,
            "[Ainos AI] Received: %s\n[Ainos AI] Tokens: %zu chars\n",
            input, strlen(input));
    }

    kfree(input);
    return len;
}

/* /proc/ai/embed 读操作 */
static ssize_t embed_read(struct file *file, char __user *buf,
                          size_t len, loff_t *off) {
    if (*off > 0) return 0;
    const char *msg = "Write text to get embedding vector.\n";
    size_t msg_len = strlen(msg);
    if (copy_to_user(buf, msg, msg_len)) return -EFAULT;
    *off += msg_len;
    return msg_len;
}

/* /proc/ai/embed 写操作 */
static ssize_t embed_write(struct file *file, const char __user *buf,
                           size_t len, loff_t *off) {
    char *input;
    if (len > BUF_SIZE - 1) return -EINVAL;
    input = kmalloc(len + 1, GFP_KERNEL);
    if (!input) return -ENOMEM;
    if (copy_from_user(input, buf, len)) { kfree(input); return -EFAULT; }
    input[len] = '\0';
    if (len > 0 && input[len-1] == '\n') input[len-1] = '\0';

    pr_info("proc-ai: embed request: %s\n", input);
    /* 模拟返回 4 维向量 */
    if (ai_output_buf) kfree(ai_output_buf);
    ai_output_buf = kmalloc(BUF_SIZE, GFP_KERNEL);
    if (ai_output_buf) {
        ai_output_len = snprintf(ai_output_buf, BUF_SIZE,
            "[0.1, 0.3, 0.7, 0.2]  // dim=4, text=\"%s\"\n", input);
    }
    kfree(input);
    return len;
}

/* /proc/ai/models 显示 */
static int models_show(struct seq_file *m, void *v) {
    seq_printf(m, "Available models:\n");
    seq_printf(m, "  - phi-3-mini-4k-instruct-q4.gguf  (local, 3.8B)\n");
    seq_printf(m, "  - nomic-embed-text-v1.gguf        (local, 137M)\n");
    seq_printf(m, "  - gpt-5.6-sol                      (cloud, Weelink)\n");
    return 0;
}
static int models_open(struct inode *inode, struct file *file) {
    return single_open(file, models_show, NULL);
}

/* /proc/ai/config 显示 */
static int config_show(struct seq_file *m, void *v) {
    seq_printf(m, "backend: hybrid\n");
    seq_printf(m, "local_engine: ggml\n");
    seq_printf(m, "cloud_endpoint: https://api.weelinking.com/v1\n");
    seq_printf(m, "power_policy: balanced\n");
    seq_printf(m, "max_tokens: 2048\n");
    seq_printf(m, "temperature: 0.7\n");
    return 0;
}
static int config_open(struct inode *inode, struct file *file) {
    return single_open(file, config_show, NULL);
}

/* 文件操作结构 */
static const struct proc_ops status_fops = {
    .proc_open    = status_open,
    .proc_read    = seq_read,
    .proc_write   = status_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static const struct proc_ops infer_fops = {
    .proc_read    = infer_read,
    .proc_write   = infer_write,
    .proc_lseek   = default_llseek,
};

static const struct proc_ops embed_fops = {
    .proc_read    = embed_read,
    .proc_write   = embed_write,
    .proc_lseek   = default_llseek,
};

static const struct proc_ops models_fops = {
    .proc_open    = models_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static const struct proc_ops config_fops = {
    .proc_open    = config_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static int __init proc_ai_init(void) {
    ai_dir = proc_mkdir(PROC_AI_DIR, NULL);
    if (!ai_dir) {
        pr_err("proc-ai: failed to create /proc/ai\n");
        return -ENOMEM;
    }

    ai_status = proc_create("status", 0644, ai_dir, &status_fops);
    ai_infer  = proc_create("infer",  0644, ai_dir, &infer_fops);
    ai_embed  = proc_create("embed",  0644, ai_dir, &embed_fops);
    ai_models = proc_create("models", 0444, ai_dir, &models_fops);
    ai_config = proc_create("config", 0444, ai_dir, &config_fops);

    if (!ai_status || !ai_infer || !ai_embed || !ai_models || !ai_config) {
        pr_err("proc-ai: failed to create proc files\n");
        remove_proc_subtree(PROC_AI_DIR, NULL);
        return -ENOMEM;
    }

    ai_output_buf = NULL;
    ai_output_len = 0;

    pr_info("proc-ai: /proc/ai mounted successfully\n");
    return 0;
}

static void __exit proc_ai_exit(void) {
    if (ai_output_buf) kfree(ai_output_buf);
    if (ai_input_buf) kfree(ai_input_buf);
    remove_proc_subtree(PROC_AI_DIR, NULL);
    pr_info("proc-ai: /proc/ai unmounted\n");
}

module_init(proc_ai_init);
module_exit(proc_ai_exit);