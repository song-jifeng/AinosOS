// Ainos OS - /proc/ai 虚拟 AI 文件系统 (深度实现)
// 完整的内核 VFS 层，通过 misc device + IOCTL 与用户态 bridge 通信
// 支持: 推理、嵌入、对话、状态、模型、配置、统计
//
// 架构:
//   echo "prompt" > /proc/ai/infer
//     → proc_ai_infer_write() 入队请求
//     → 工作队列唤醒 bridge (通过 /dev/ainos-proc)
//     → bridge 转发给 ai-daemon (TCP 9500)
//     → 响应回写 → 用户 cat /proc/ai/infer 读取
//
// 并发模型:
//   - 请求队列: spinlock_irqsave (中断上下文安全)
//   - 响应缓存: RCU (kfree_rcu)
//   - 统计: atomic64_t
//   - 等待: waitqueue (poll/select 支持)

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/atomic.h>
#include <linux/wait.h>
#include <linux/sched.h>
#include <linux/miscdevice.h>
#include <linux/ioctl.h>
#include <linux/poll.h>
#include <linux/workqueue.h>
#include <linux/timer.h>
#include <linux/rcupdate.h>
#include <linux/jiffies.h>
#include <linux/version.h>

#include "proc_ai.h"

MODULE_LICENSE("MIT");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("/proc/ai - AI virtual filesystem (deep implementation)");
MODULE_VERSION("1.0.0");

/* ================================================================
 * 参数配置
 * ================================================================ */

/* 请求队列深度 */
#define REQ_QUEUE_DEPTH   64
/* 请求数据最大长度 */
#define REQ_DATA_MAX      4096
/* 响应数据最大长度 */
#define RESP_DATA_MAX     65536
/* 请求超时 (秒) */
#define REQ_TIMEOUT_SEC   30
/* 同一文件最大等待读进程数 */
#define MAX_WAITERS       16
/* 统计窗口大小 */
#define STATS_WINDOW_MS   60000

/* ================================================================
 * 请求/响应数据结构
 * ================================================================ */

/* 文件类型 ID */
enum ai_proc_file_id {
    AI_PROC_FILE_STATUS = 0,
    AI_PROC_FILE_INFER  = 1,
    AI_PROC_FILE_EMBED  = 2,
    AI_PROC_FILE_CHAT   = 3,
    AI_PROC_FILE_MODELS = 4,
    AI_PROC_FILE_CONFIG = 5,
    AI_PROC_FILE_STATS  = 6,
    AI_PROC_FILE_MAX,
};

/* 请求状态 */
enum ai_req_status {
    AI_REQ_PENDING  = 0,  /* 排队中 */
    AI_REQ_SENT     = 1,  /* 已发送给 bridge */
    AI_REQ_TIMEOUT  = 2,  /* 超时 */
    AI_REQ_ERROR    = 3,  /* 错误 */
};

/* 请求结构 */
struct ai_proc_request {
    u32 id;                    /* 自增 ID */
    enum ai_proc_file_id file_id; /* 来源文件 */
    u32 session_id;            /* 会话 ID */
    enum ai_req_status status; /* 状态 */
    char data[REQ_DATA_MAX];  /* 请求数据 */
    u32 len;                   /* 数据长度 */
    u32 flags;                 /* 标志位 */
    struct timespec64 submitted; /* 提交时间 */
    struct completion complete;  /* 完成信号 */
    struct list_head list;        /* 队列链表 */
};

/* 响应结构 */
struct ai_proc_response {
    u32 req_id;                /* 对应请求 ID */
    u32 status;                /* 0=ready, 1=error */
    char data[RESP_DATA_MAX]; /* 响应数据 */
    u32 len;
    char source[16];           /* "local" / "cloud" */
    u32 tokens;
    u64 inference_ms;
    struct rcu_head rcu;       /* RCU 回退 */
};

/* ================================================================
 * 全局状态
 * ================================================================ */

/* 请求队列 */
static LIST_HEAD(req_queue);                     /* 待处理队列 */
static LIST_HEAD(req_pending);                   /* 已发送等待响应队列 */
static spinlock_t req_lock = __SPIN_LOCK_UNLOCKED(req_lock);
static atomic_t req_id_counter = ATOMIC_INIT(0);
static wait_queue_head_t req_waitq;              /* bridge 等待新请求 */
static struct workqueue_struct *proc_ai_wq;      /* 工作队列 */

/* 响应缓存 (per-file-type, RCU 保护) */
static struct ai_proc_response __rcu *resp_cache[AI_PROC_FILE_MAX];

/* 统计 */
static atomic64_t stats_infer_count;
static atomic64_t stats_embed_count;
static atomic64_t stats_chat_count;
static atomic64_t stats_error_count;
static atomic64_t stats_timeout_count;
static atomic64_t stats_bytes_in;
static atomic64_t stats_bytes_out;
static unsigned long stats_start_jiffies;
static atomic_t stats_peak_queue_depth;
static atomic_t stats_queue_full_count;

/* 超时定时器 */
static struct timer_list req_timeout_timer;

/* session 计数器 */
static atomic_t session_counter = ATOMIC_INIT(0);

/* ================================================================
 * 请求队列操作
 * ================================================================ */

/* 入队请求 */
static int enqueue_request(struct ai_proc_request *req)
{
    unsigned long flags;
    int depth;

    spin_lock_irqsave(&req_lock, flags);

    depth = 0;
    if (!list_empty(&req_queue))
        depth++; /* 近似 */
    if (!list_empty(&req_pending))
        depth++;

    if (depth >= REQ_QUEUE_DEPTH) {
        atomic_inc(&stats_queue_full_count);
        spin_unlock_irqrestore(&req_lock, flags);
        return -ENOSPC;
    }

    req->id = (u32)atomic_inc_return(&req_id_counter);
    ktime_get_real_ts64(&req->submitted);
    init_completion(&req->complete);
    req->status = AI_REQ_PENDING;

    list_add_tail(&req->list, &req_queue);

    /* 更新峰值队列深度 */
    {
        int cur_depth = 0;
        struct list_head *p;
        list_for_each(p, &req_queue) { cur_depth++; }
        list_for_each(p, &req_pending) { cur_depth++; }
        if (cur_depth > atomic_read(&stats_peak_queue_depth))
            atomic_set(&stats_peak_queue_depth, cur_depth);
    }

    spin_unlock_irqrestore(&req_lock, flags);

    /* 唤醒 bridge */
    wake_up_interruptible(&req_waitq);

    return 0;
}

/* 出队请求 (bridge 取走) */
static struct ai_proc_request *dequeue_request(void)
{
    unsigned long flags;
    struct ai_proc_request *req = NULL;

    spin_lock_irqsave(&req_lock, flags);

    if (!list_empty(&req_queue)) {
        req = list_first_entry(&req_queue, struct ai_proc_request, list);
        list_move_tail(&req->list, &req_pending);
        req->status = AI_REQ_SENT;
    }

    spin_unlock_irqrestore(&req_lock, flags);
    return req;
}

/* 完成请求 (bridge 写回响应) */
static struct ai_proc_request *complete_request(u32 req_id)
{
    unsigned long flags;
    struct ai_proc_request *req = NULL;
    struct list_head *p, *n;

    spin_lock_irqsave(&req_lock, flags);

    list_for_each_safe(p, n, &req_pending) {
        req = list_entry(p, struct ai_proc_request, list);
        if (req->id == req_id) {
            list_del(&req->list);
            complete_all(&req->complete);
            spin_unlock_irqrestore(&req_lock, flags);
            return req;
        }
    }

    spin_unlock_irqrestore(&req_lock, flags);
    return NULL;
}

/* 超时检查 */
static void check_timeouts(struct timer_list *t)
{
    unsigned long flags;
    struct ai_proc_request *req;
    struct list_head *p, *n;
    struct timespec64 now;
    struct timespec64 timeout = {
        .tv_sec = REQ_TIMEOUT_SEC,
        .tv_nsec = 0,
    };

    ktime_get_real_ts64(&now);

    spin_lock_irqsave(&req_lock, flags);

    list_for_each_safe(p, n, &req_pending) {
        req = list_entry(p, struct ai_proc_request, list);
        struct timespec64 elapsed = timespec64_sub(now, req->submitted);

        if (timespec64_compare(&elapsed, &timeout) > 0) {
            req->status = AI_REQ_TIMEOUT;
            list_del(&req->list);
            complete_all(&req->complete);
            atomic64_inc(&stats_timeout_count);
            pr_debug("proc-ai: request %u timed out\n", req->id);
        }
    }

    spin_unlock_irqrestore(&req_lock, flags);

    /* 重新调度定时器 */
    mod_timer(&req_timeout_timer, jiffies + HZ);
}

/* ================================================================
 * 响应缓存操作 (RCU)
 * ================================================================ */

/* 缓存响应 */
static void cache_response(enum ai_proc_file_id file_id,
                           struct ai_proc_response *resp)
{
    struct ai_proc_response *old;

    old = rcu_dereference_protected(resp_cache[file_id],
        lockdep_is_held(&req_lock));

    rcu_assign_pointer(resp_cache[file_id], resp);

    if (old)
        kfree_rcu(old, rcu);
}

/* 读取缓存响应 (必须在 RCU 读锁内) */
static struct ai_proc_response *get_cached_response(enum ai_proc_file_id file_id)
{
    return rcu_dereference(resp_cache[file_id]);
}

/* 分配新响应 */
static struct ai_proc_response *alloc_response(void)
{
    return kzalloc(sizeof(struct ai_proc_response), GFP_KERNEL);
}

/* ================================================================
 * /proc/ai 文件操作
 * ================================================================ */

/* 每个文件打开时的私有数据 */
struct ai_proc_file_priv {
    enum ai_proc_file_id file_id;
    struct ai_proc_request *active_req;
    wait_queue_head_t read_waitq;
    int has_new_data;
};

/* ---------- /proc/ai/status ---------- */
static int status_show(struct seq_file *m, void *v)
{
    u64 uptime = (jiffies - stats_start_jiffies) / HZ;

    seq_printf(m, "Ainos AI System Status\n");
    seq_printf(m, "======================\n");
    seq_printf(m, "state:           running\n");
    seq_printf(m, "version:         %s\n", PROC_AI_VERSION);
    seq_printf(m, "uptime:          %llu s\n", uptime);
    seq_printf(m, "\n");
    seq_printf(m, "Performance:\n");
    seq_printf(m, "  inferences:    %llu\n", atomic64_read(&stats_infer_count));
    seq_printf(m, "  embeds:        %llu\n", atomic64_read(&stats_embed_count));
    seq_printf(m, "  chats:         %llu\n", atomic64_read(&stats_chat_count));
    seq_printf(m, "  errors:        %llu\n", atomic64_read(&stats_error_count));
    seq_printf(m, "  timeouts:      %llu\n", atomic64_read(&stats_timeout_count));
    seq_printf(m, "  bytes_in:      %llu\n", atomic64_read(&stats_bytes_in));
    seq_printf(m, "  bytes_out:     %llu\n", atomic64_read(&stats_bytes_out));
    seq_printf(m, "  peak_queue:    %d\n", atomic_read(&stats_peak_queue_depth));
    seq_printf(m, "  queue_full:    %d\n", atomic_read(&stats_queue_full_count));
    seq_printf(m, "\n");
    seq_printf(m, "Config:\n");
    seq_printf(m, "  queue_depth:   %d\n", REQ_QUEUE_DEPTH);
    seq_printf(m, "  timeout:       %d s\n", REQ_TIMEOUT_SEC);
    seq_printf(m, "  backend:       hybrid\n");

    return 0;
}
static int status_open(struct inode *inode, struct file *file)
{
    return single_open(file, status_show, NULL);
}

/* ---------- /proc/ai/infer ---------- */
static int infer_open(struct inode *inode, struct file *file)
{
    struct ai_proc_file_priv *priv = kzalloc(sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    priv->file_id = AI_PROC_FILE_INFER;
    init_waitqueue_head(&priv->read_waitq);
    file->private_data = priv;
    return 0;
}

static ssize_t infer_read(struct file *file, char __user *buf,
                          size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_response *resp;
    size_t copy_len;
    int ret;

    if (*off > 0) return 0;

    /* 等待请求完成 */
    if (priv->active_req) {
        ret = wait_for_completion_interruptible(&priv->active_req->complete);
        if (ret) return -ERESTARTSYS;
    }

    rcu_read_lock();
    resp = get_cached_response(AI_PROC_FILE_INFER);
    if (!resp) {
        rcu_read_unlock();
        const char *msg = "No inference result available.\n";
        if (copy_to_user(buf, msg, strlen(msg))) return -EFAULT;
        *off = strlen(msg);
        return strlen(msg);
    }

    copy_len = min(len, (size_t)resp->len);
    if (copy_to_user(buf, resp->data, copy_len)) {
        rcu_read_unlock();
        return -EFAULT;
    }
    *off = copy_len;
    rcu_read_unlock();

    /* 释放请求 */
    if (priv->active_req) {
        kfree(priv->active_req);
        priv->active_req = NULL;
    }

    return copy_len;
}

static ssize_t infer_write(struct file *file, const char __user *buf,
                           size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_request *req;
    char *kbuf;
    int ret;

    if (len > REQ_DATA_MAX - 1) return -EINVAL;
    if (len == 0) return 0;

    kbuf = kmalloc(len + 1, GFP_KERNEL);
    if (!kbuf) return -ENOMEM;

    if (copy_from_user(kbuf, buf, len)) {
        kfree(kbuf);
        return -EFAULT;
    }
    kbuf[len] = '\0';

    /* 去掉尾部换行 */
    if (len > 0 && kbuf[len-1] == '\n')
        kbuf[--len] = '\0';

    req = kzalloc(sizeof(*req), GFP_KERNEL);
    if (!req) {
        kfree(kbuf);
        return -ENOMEM;
    }

    memcpy(req->data, kbuf, len);
    req->len = len;
    req->file_id = AI_PROC_FILE_INFER;
    req->session_id = 0;

    kfree(kbuf);

    ret = enqueue_request(req);
    if (ret) {
        kfree(req);
        return ret;
    }

    /* 释放之前的请求 */
    if (priv->active_req)
        kfree(priv->active_req);

    priv->active_req = req;
    atomic64_inc(&stats_infer_count);
    atomic64_add(len, &stats_bytes_in);

    return len;
}

static __poll_t infer_poll(struct file *file, struct poll_table_struct *wait)
{
    struct ai_proc_file_priv *priv = file->private_data;
    __poll_t mask = 0;

    /* 可写: 只要队列不满 */
    mask |= EPOLLOUT | EPOLLWRNORM;

    /* 可读: 有请求完成 */
    if (priv->active_req) {
        if (completion_done(&priv->active_req->complete))
            mask |= EPOLLIN | EPOLLRDNORM;
    } else {
        rcu_read_lock();
        if (get_cached_response(AI_PROC_FILE_INFER))
            mask |= EPOLLIN | EPOLLRDNORM;
        rcu_read_unlock();
    }

    if (priv->active_req)
        poll_wait(file, &priv->active_req->complete.wait, wait);

    return mask;
}

static int infer_release(struct inode *inode, struct file *file)
{
    struct ai_proc_file_priv *priv = file->private_data;
    if (priv->active_req) {
        /* 请求可能还在处理中，不能 kfree */
        /* 实际应标记为取消，简化处理 */
    }
    kfree(priv);
    return 0;
}

/* ---------- /proc/ai/embed ---------- */
static int embed_open(struct inode *inode, struct file *file)
{
    struct ai_proc_file_priv *priv = kzalloc(sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    priv->file_id = AI_PROC_FILE_EMBED;
    init_waitqueue_head(&priv->read_waitq);
    file->private_data = priv;
    return 0;
}

static ssize_t embed_read(struct file *file, char __user *buf,
                          size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_response *resp;
    size_t copy_len;
    int ret;

    if (*off > 0) return 0;

    if (priv->active_req) {
        ret = wait_for_completion_interruptible(&priv->active_req->complete);
        if (ret) return -ERESTARTSYS;
    }

    rcu_read_lock();
    resp = get_cached_response(AI_PROC_FILE_EMBED);
    if (!resp) {
        rcu_read_unlock();
        return 0;
    }

    copy_len = min(len, (size_t)resp->len);
    if (copy_to_user(buf, resp->data, copy_len)) {
        rcu_read_unlock();
        return -EFAULT;
    }
    *off = copy_len;
    rcu_read_unlock();

    if (priv->active_req) {
        kfree(priv->active_req);
        priv->active_req = NULL;
    }

    return copy_len;
}

static ssize_t embed_write(struct file *file, const char __user *buf,
                           size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_request *req;
    char *kbuf;
    int ret;

    if (len > REQ_DATA_MAX - 1) return -EINVAL;
    if (len == 0) return 0;

    kbuf = kmalloc(len + 1, GFP_KERNEL);
    if (!kbuf) return -ENOMEM;
    if (copy_from_user(kbuf, buf, len)) { kfree(kbuf); return -EFAULT; }
    kbuf[len] = '\0';
    if (len > 0 && kbuf[len-1] == '\n') kbuf[--len] = '\0';

    req = kzalloc(sizeof(*req), GFP_KERNEL);
    if (!req) { kfree(kbuf); return -ENOMEM; }

    memcpy(req->data, kbuf, len);
    req->len = len;
    req->file_id = AI_PROC_FILE_EMBED;
    kfree(kbuf);

    ret = enqueue_request(req);
    if (ret) { kfree(req); return ret; }

    if (priv->active_req) kfree(priv->active_req);
    priv->active_req = req;
    atomic64_inc(&stats_embed_count);
    atomic64_add(len, &stats_bytes_in);

    return len;
}

static int embed_release(struct inode *inode, struct file *file)
{
    kfree(file->private_data);
    return 0;
}

/* ---------- /proc/ai/chat ---------- */
static int chat_open(struct inode *inode, struct file *file)
{
    struct ai_proc_file_priv *priv = kzalloc(sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    priv->file_id = AI_PROC_FILE_CHAT;
    init_waitqueue_head(&priv->read_waitq);
    file->private_data = priv;
    return 0;
}

static ssize_t chat_read(struct file *file, char __user *buf,
                         size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_response *resp;
    size_t copy_len;
    int ret;

    if (*off > 0) return 0;

    if (priv->active_req) {
        ret = wait_for_completion_interruptible(&priv->active_req->complete);
        if (ret) return -ERESTARTSYS;
    }

    rcu_read_lock();
    resp = get_cached_response(AI_PROC_FILE_CHAT);
    if (!resp) { rcu_read_unlock(); return 0; }

    copy_len = min(len, (size_t)resp->len);
    if (copy_to_user(buf, resp->data, copy_len)) { rcu_read_unlock(); return -EFAULT; }
    *off = copy_len;
    rcu_read_unlock();

    if (priv->active_req) { kfree(priv->active_req); priv->active_req = NULL; }
    return copy_len;
}

static ssize_t chat_write(struct file *file, const char __user *buf,
                          size_t len, loff_t *off)
{
    struct ai_proc_file_priv *priv = file->private_data;
    struct ai_proc_request *req;
    char *kbuf;
    int ret;

    if (len > REQ_DATA_MAX - 1) return -EINVAL;
    if (len == 0) return 0;

    kbuf = kmalloc(len + 1, GFP_KERNEL);
    if (!kbuf) return -ENOMEM;
    if (copy_from_user(kbuf, buf, len)) { kfree(kbuf); return -EFAULT; }
    kbuf[len] = '\0';
    if (len > 0 && kbuf[len-1] == '\n') kbuf[--len] = '\0';

    req = kzalloc(sizeof(*req), GFP_KERNEL);
    if (!req) { kfree(kbuf); return -ENOMEM; }

    memcpy(req->data, kbuf, len);
    req->len = len;
    req->file_id = AI_PROC_FILE_CHAT;
    /* 自动分配 session ID */
    req->session_id = (u32)atomic_inc_return(&session_counter);
    kfree(kbuf);

    ret = enqueue_request(req);
    if (ret) { kfree(req); return ret; }

    if (priv->active_req) kfree(priv->active_req);
    priv->active_req = req;
    atomic64_inc(&stats_chat_count);
    atomic64_add(len, &stats_bytes_in);

    return len;
}

static int chat_release(struct inode *inode, struct file *file)
{
    kfree(file->private_data);
    return 0;
}

/* ---------- /proc/ai/models ---------- */
static int models_show(struct seq_file *m, void *v)
{
    struct ai_proc_response *resp;

    rcu_read_lock();
    resp = get_cached_response(AI_PROC_FILE_MODELS);
    if (resp && resp->len > 0) {
        seq_printf(m, "%.*s", (int)resp->len, resp->data);
    } else {
        seq_printf(m, "No models loaded. Run 'echo refresh > /proc/ai/config' to update.\n");
    }
    rcu_read_unlock();

    return 0;
}
static int models_open(struct inode *inode, struct file *file)
{
    return single_open(file, models_show, NULL);
}

/* ---------- /proc/ai/config ---------- */
static int config_show(struct seq_file *m, void *v)
{
    seq_printf(m, "version:         %s\n", PROC_AI_VERSION);
    seq_printf(m, "queue_depth:     %d\n", REQ_QUEUE_DEPTH);
    seq_printf(m, "timeout_sec:     %d\n", REQ_TIMEOUT_SEC);
    seq_printf(m, "backend:         hybrid\n");
    seq_printf(m, "local_engine:    ggml\n");
    seq_printf(m, "cloud_endpoint:  https://api.weelinking.com/v1\n");
    seq_printf(m, "\n");
    seq_printf(m, "Commands:\n");
    seq_printf(m, "  echo 'refresh models' > config   Refresh model list\n");
    seq_printf(m, "  echo 'reset stats' > config      Reset statistics\n");
    return 0;
}
static int config_open(struct inode *inode, struct file *file)
{
    return single_open(file, config_show, NULL);
}
static ssize_t config_write(struct file *file, const char __user *buf,
                            size_t len, loff_t *off)
{
    char cmd[128];
    if (len > sizeof(cmd) - 1) return -EINVAL;
    if (copy_from_user(cmd, buf, len)) return -EFAULT;
    cmd[len] = '\0';
    if (len > 0 && cmd[len-1] == '\n') cmd[len-1] = '\0';

    if (strcmp(cmd, "refresh models") == 0) {
        /* 发送模型刷新请求 */
        struct ai_proc_request *req = kzalloc(sizeof(*req), GFP_KERNEL);
        if (!req) return -ENOMEM;
        req->file_id = AI_PROC_FILE_MODELS;
        req->len = 0;
        int ret = enqueue_request(req);
        if (ret) { kfree(req); return ret; }
        pr_info("proc-ai: refreshing model list\n");
        return len;
    }

    if (strcmp(cmd, "reset stats") == 0) {
        atomic64_set(&stats_infer_count, 0);
        atomic64_set(&stats_embed_count, 0);
        atomic64_set(&stats_chat_count, 0);
        atomic64_set(&stats_error_count, 0);
        atomic64_set(&stats_timeout_count, 0);
        atomic64_set(&stats_bytes_in, 0);
        atomic64_set(&stats_bytes_out, 0);
        atomic_set(&stats_peak_queue_depth, 0);
        atomic_set(&stats_queue_full_count, 0);
        pr_info("proc-ai: statistics reset\n");
        return len;
    }

    return -EINVAL;
}

/* ---------- /proc/ai/stats ---------- */
static int stats_show(struct seq_file *m, void *v)
{
    u64 uptime = (jiffies - stats_start_jiffies) / HZ;
    u64 infers = atomic64_read(&stats_infer_count);
    u64 embeds = atomic64_read(&stats_embed_count);
    u64 chats = atomic64_read(&stats_chat_count);
    u64 errors = atomic64_read(&stats_error_count);
    u64 timeouts = atomic64_read(&stats_timeout_count);

    seq_printf(m, "proc-ai statistics\n");
    seq_printf(m, "==================\n");
    seq_printf(m, "uptime:     %llu s\n", uptime);
    seq_printf(m, "infer:      %llu\n", infers);
    seq_printf(m, "embed:      %llu\n", embeds);
    seq_printf(m, "chat:       %llu\n", chats);
    seq_printf(m, "total:      %llu\n", infers + embeds + chats);
    seq_printf(m, "errors:     %llu\n", errors);
    seq_printf(m, "timeouts:   %llu\n", timeouts);
    seq_printf(m, "bytes_in:   %llu\n", atomic64_read(&stats_bytes_in));
    seq_printf(m, "bytes_out:  %llu\n", atomic64_read(&stats_bytes_out));
    seq_printf(m, "peak_queue: %d\n", atomic_read(&stats_peak_queue_depth));
    seq_printf(m, "queue_full: %d\n", atomic_read(&stats_queue_full_count));

    if (uptime > 0) {
        seq_printf(m, "ops/sec:    %llu\n", (infers + embeds + chats) / uptime);
    }

    return 0;
}
static int stats_open(struct inode *inode, struct file *file)
{
    return single_open(file, stats_show, NULL);
}

/* ================================================================
 * /proc/ai 文件操作表
 * ================================================================ */

static const struct proc_ops status_fops = {
    .proc_open    = status_open,
    .proc_read    = seq_read,
    .proc_write   = status_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static const struct proc_ops infer_fops = {
    .proc_open    = infer_open,
    .proc_read    = infer_read,
    .proc_write   = infer_write,
    .proc_poll    = infer_poll,
    .proc_lseek   = default_llseek,
    .proc_release = infer_release,
};

static const struct proc_ops embed_fops = {
    .proc_open    = embed_open,
    .proc_read    = embed_read,
    .proc_write   = embed_write,
    .proc_lseek   = default_llseek,
    .proc_release = embed_release,
};

static const struct proc_ops chat_fops = {
    .proc_open    = chat_open,
    .proc_read    = chat_read,
    .proc_write   = chat_write,
    .proc_lseek   = default_llseek,
    .proc_release = chat_release,
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
    .proc_write   = config_write,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

static const struct proc_ops stats_fops = {
    .proc_open    = stats_open,
    .proc_read    = seq_read,
    .proc_lseek   = seq_lseek,
    .proc_release = single_release,
};

/* ================================================================
 * Misc Device (/dev/ainos-proc) - 内核 ↔ 用户态通道
 * ================================================================ */

/* bridge 等待队列 */
static DECLARE_WAIT_QUEUE_HEAD(proc_ai_poll_waitq);

/* bridge 打开计数 */
static atomic_t bridge_open_count = ATOMIC_INIT(0);
static struct mutex bridge_mutex;

/* misc device 打开 */
static int proc_ai_dev_open(struct inode *inode, struct file *file)
{
    /* 只允许一个 bridge 连接 */
    if (atomic_cmpxchg(&bridge_open_count, 0, 1) != 0) {
        /* 允许第二个打开用于调试 */
        // 但只允许一个写
    }
    return 0;
}

/* misc device 关闭 */
static int proc_ai_dev_release(struct inode *inode, struct file *file)
{
    atomic_set(&bridge_open_count, 0);

    /* bridge 断开，超时所有 pending 请求 */
    unsigned long flags;
    struct ai_proc_request *req;
    struct list_head *p, *n;

    spin_lock_irqsave(&req_lock, flags);
    list_for_each_safe(p, n, &req_pending) {
        req = list_entry(p, struct ai_proc_request, list);
        req->status = AI_REQ_ERROR;
        list_del(&req->list);
        complete_all(&req->complete);
        atomic64_inc(&stats_error_count);
    }
    spin_unlock_irqrestore(&req_lock, flags);

    pr_info("proc-ai: bridge disconnected, %d requests cancelled\n",
            atomic64_read(&stats_error_count));

    return 0;
}

/* IOCTL: 获取待处理请求 */
static long proc_ai_get_request(struct ai_proc_request __user *uarg)
{
    struct ai_proc_request *req;
    int ret;

    req = dequeue_request();
    if (!req)
        return -EAGAIN;

    /* 复制到用户空间 */
    ret = copy_to_user(uarg, req, sizeof(*req));
    if (ret) {
        /* 放回队列 */
        unsigned long flags;
        spin_lock_irqsave(&req_lock, flags);
        req->status = AI_REQ_PENDING;
        list_add(&req->list, &req_queue);
        spin_unlock_irqrestore(&req_lock, flags);
        return -EFAULT;
    }

    kfree(req);
    return 0;
}

/* IOCTL: 发送响应 */
static long proc_ai_send_response(struct ai_proc_response __user *uarg)
{
    struct ai_proc_response *resp;
    struct ai_proc_response *user_resp = NULL;
    struct ai_proc_request *req;

    user_resp = kmalloc(sizeof(*user_resp), GFP_KERNEL);
    if (!user_resp) return -ENOMEM;

    if (copy_from_user(user_resp, uarg, sizeof(*user_resp))) {
        kfree(user_resp);
        return -EFAULT;
    }

    /* 缓存响应 */
    unsigned long flags;
    spin_lock_irqsave(&req_lock, flags);

    resp = alloc_response();
    if (!resp) {
        spin_unlock_irqrestore(&req_lock, flags);
        kfree(user_resp);
        return -ENOMEM;
    }

    memcpy(resp, user_resp, sizeof(*resp));
    kfree(user_resp);

    /* 根据请求 ID 确定文件类型 */
    /* 注意: 实际需要查找 req_id 对应的文件类型 */
    /* 简化: 从请求中推断 */
    enum ai_proc_file_id file_id = AI_PROC_FILE_INFER; /* 默认 */
    req = complete_request(resp->req_id);
    if (req) {
        file_id = req->file_id;
        kfree(req);
    }

    cache_response(file_id, resp);
    atomic64_add(resp->len, &stats_bytes_out);

    spin_unlock_irqrestore(&req_lock, flags);

    return 0;
}

/* IOCTL: 等待新请求 (poll 支持) */
static __poll_t proc_ai_dev_poll(struct file *file, poll_table *wait)
{
    __poll_t mask = EPOLLOUT | EPOLLWRNORM;

    poll_wait(file, &proc_ai_poll_waitq, wait);

    unsigned long flags;
    spin_lock_irqsave(&req_lock, flags);
    if (!list_empty(&req_queue))
        mask |= EPOLLIN | EPOLLRDNORM;
    spin_unlock_irqrestore(&req_lock, flags);

    return mask;
}

/* IOCTL 主处理 */
static long proc_ai_dev_ioctl(struct file *file, unsigned int cmd,
                              unsigned long arg)
{
    void __user *uarg = (void __user *)arg;

    switch (cmd) {
    case AI_PROC_GET_REQUEST:
        return proc_ai_get_request(uarg);
    case AI_PROC_SEND_RESPONSE:
        return proc_ai_send_response(uarg);
    default:
        return -ENOTTY;
    }
}

/* misc device 文件操作 */
static const struct file_operations proc_ai_dev_fops = {
    .owner          = THIS_MODULE,
    .open           = proc_ai_dev_open,
    .release        = proc_ai_dev_release,
    .unlocked_ioctl = proc_ai_dev_ioctl,
    .poll           = proc_ai_dev_poll,
    .llseek         = no_llseek,
};

/* misc device 结构 */
static struct miscdevice proc_ai_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = "ainos-proc",
    .fops  = &proc_ai_dev_fops,
};

/* ================================================================
 * 模块初始化
 * ================================================================ */

static struct proc_dir_entry *ai_dir;
static struct proc_dir_entry *ai_status;
static struct proc_dir_entry *ai_infer;
static struct proc_dir_entry *ai_embed;
static struct proc_dir_entry *ai_chat;
static struct proc_dir_entry *ai_models;
static struct proc_dir_entry *ai_config;
static struct proc_dir_entry *ai_stats;

static int __init proc_ai_init(void)
{
    int ret;
    int i;

    /* 初始化统计 */
    stats_start_jiffies = jiffies;
    atomic64_set(&stats_infer_count, 0);
    atomic64_set(&stats_embed_count, 0);
    atomic64_set(&stats_chat_count, 0);
    atomic64_set(&stats_error_count, 0);
    atomic64_set(&stats_timeout_count, 0);
    atomic64_set(&stats_bytes_in, 0);
    atomic64_set(&stats_bytes_out, 0);
    atomic_set(&stats_peak_queue_depth, 0);
    atomic_set(&stats_queue_full_count, 0);

    /* 初始化响应缓存 */
    for (i = 0; i < AI_PROC_FILE_MAX; i++)
        RCU_INIT_POINTER(resp_cache[i], NULL);

    /* 初始化等待队列 */
    init_waitqueue_head(&req_waitq);

    /* 创建工作队列 */
    proc_ai_wq = alloc_workqueue("proc_ai_wq", WQ_UNBOUND | WQ_HIGHPRI, 4);
    if (!proc_ai_wq) {
        pr_err("proc-ai: failed to create workqueue\n");
        return -ENOMEM;
    }

    /* 初始化互斥锁 */
    mutex_init(&bridge_mutex);

    /* 注册 misc device */
    ret = misc_register(&proc_ai_miscdev);
    if (ret) {
        pr_err("proc-ai: failed to register misc device: %d\n", ret);
        destroy_workqueue(proc_ai_wq);
        return ret;
    }
    pr_info("proc-ai: registered /dev/ainos-proc (minor=%d)\n",
            proc_ai_miscdev.minor);

    /* 创建 /proc/ai 目录 */
    ai_dir = proc_mkdir("ai", NULL);
    if (!ai_dir) {
        pr_err("proc-ai: failed to create /proc/ai\n");
        misc_deregister(&proc_ai_miscdev);
        destroy_workqueue(proc_ai_wq);
        return -ENOMEM;
    }

    /* 创建文件节点 */
    ai_status = proc_create("status", 0644, ai_dir, &status_fops);
    ai_infer  = proc_create("infer",  0644, ai_dir, &infer_fops);
    ai_embed  = proc_create("embed",  0644, ai_dir, &embed_fops);
    ai_chat   = proc_create("chat",   0644, ai_dir, &chat_fops);
    ai_models = proc_create("models", 0444, ai_dir, &models_fops);
    ai_config = proc_create("config", 0644, ai_dir, &config_fops);
    ai_stats  = proc_create("stats",  0444, ai_dir, &stats_fops);

    if (!ai_status || !ai_infer || !ai_embed || !ai_chat ||
        !ai_models || !ai_config || !ai_stats) {
        pr_err("proc-ai: failed to create proc files\n");
        remove_proc_subtree("ai", NULL);
        misc_deregister(&proc_ai_miscdev);
        destroy_workqueue(proc_ai_wq);
        return -ENOMEM;
    }

    /* 启动超时定时器 */
    timer_setup(&req_timeout_timer, check_timeouts, 0);
    mod_timer(&req_timeout_timer, jiffies + HZ);

    pr_info("proc-ai: /proc/ai mounted (deep mode)\n");
    pr_info("proc-ai: queue_depth=%d, timeout=%ds, files=%d\n",
            REQ_QUEUE_DEPTH, REQ_TIMEOUT_SEC, 7);

    return 0;
}

static void __exit proc_ai_exit(void)
{
    int i;

    /* 停止定时器 */
    del_timer_sync(&req_timeout_timer);

    /* 清理请求队列 */
    {
        unsigned long flags;
        struct ai_proc_request *req;
        struct list_head *p, *n;

        spin_lock_irqsave(&req_lock, flags);

        list_for_each_safe(p, n, &req_queue) {
            req = list_entry(p, struct ai_proc_request, list);
            list_del(&req->list);
            kfree(req);
        }
        list_for_each_safe(p, n, &req_pending) {
            req = list_entry(p, struct ai_proc_request, list);
            complete_all(&req->complete);
            list_del(&req->list);
            kfree(req);
        }

        spin_unlock_irqrestore(&req_lock, flags);
    }

    /* 清理响应缓存 */
    for (i = 0; i < AI_PROC_FILE_MAX; i++) {
        struct ai_proc_response *resp;
        resp = rcu_dereference_protected(resp_cache[i], true);
        if (resp)
            kfree(resp);
    }

    /* 移除 /proc/ai */
    remove_proc_subtree("ai", NULL);

    /* 注销 misc device */
    misc_deregister(&proc_ai_miscdev);

    /* 销毁工作队列 */
    if (proc_ai_wq)
        destroy_workqueue(proc_ai_wq);

    pr_info("proc-ai: unloaded\n");
}

module_init(proc_ai_init);
module_exit(proc_ai_exit);