// SPDX-License-Identifier: GPL-2.0
/*
 * Ainos OS - AI 任务调度器内核模块
 * ==========================================
 * 管理 AI 推理任务的优先级排队和执行
 *
 * 功能:
 *   1. 多级优先级队列 (FIFO + 优先级抢占)
 *   2. GPU/NPU 资源调度
 *   3. 任务超时和取消
 *   4. 负载统计和监控
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/sched.h>
#include <linux/wait.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/mutex.h>
#include <linux/kthread.h>
#include <linux/delay.h>
#include <linux/jiffies.h>
#include <linux/atomic.h>
#include <linux/ktime.h>
#include <linux/list.h>
#include <linux/workqueue.h>

#include "ainos/ai-abi.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Ainos OS Team");
MODULE_DESCRIPTION("Ainos AI Task Scheduler");
MODULE_VERSION("0.1.0");

/* ============================================
 * 配置参数
 * ============================================ */
#define AI_SCHED_MAX_QUEUED     4096    /* 最大排队任务数 */
#define AI_SCHED_THREAD_POOL    4       /* 工作线程数 */
#define AI_SCHED_MAX_RUNTIME_MS 60000   /* 单任务最大运行时间 (60s) */
#define AI_SCHED_WATCHDOG_MS    1000    /* 看门狗间隔 */

/* 电源策略配置 */
#define AI_THERMAL_PATH         "/sys/class/thermal/thermal_zone0/temp"
#define AI_THERMAL_POLL_MS      2000    /* 温度轮询间隔 */
#define AI_TEMP_COOL_MAX        70000   /* < 70°C: 全速模式 (毫摄氏度) */
#define AI_TEMP_WARM_MAX        85000   /* 70-85°C: 平衡模式 */
#define AI_TEMP_HOT_MAX         95000   /* 85-95°C: 节能模式 */
#define AI_TEMP_CRITICAL       95000   /* > 95°C: 紧急模式 */

/* 各模式线程数 */
static const int mode_threads[] = {
    [AI_POWER_MAX]       = 4,  /* 全速 */
    [AI_POWER_BALANCED]  = 2,  /* 平衡 */
    [AI_POWER_EFFICIENT] = 1,  /* 节能 */
    [AI_POWER_EMERGENCY] = 1,  /* 紧急 */
};

/* 每优先级队列容量 */
static const int queue_capacity[] = {
    [AI_PRIO_BACKGROUND] = 2048,
    [AI_PRIO_LOW]        = 1024,
    [AI_PRIO_NORMAL]     = 512,
    [AI_PRIO_HIGH]       = 256,
    [AI_PRIO_REALTIME]   = 64,
};

/* ============================================
 * 数据结构
 * ============================================ */

/* 任务跟踪表大小 */
#define AI_TASK_TRACK_SIZE 2048

/* AI 推理任务 */
struct ai_task {
    struct list_head node;           /* 队列节点 */
    uint64_t task_id;                /* 任务 ID */
    uint64_t model_id;               /* 模型 ID */
    enum ai_task_priority priority;  /* 优先级 */
    enum ai_task_status status;      /* 状态 */

    /* 输入输出 */
    struct ai_inference_req req;     /* 请求参数 */
    struct ai_inference_resp resp;   /* 响应数据 */

    /* 时间戳 */
    ktime_t enqueue_time;            /* 入队时间 */
    ktime_t start_time;              /* 开始时间 */
    ktime_t deadline;                /* 截止时间 */

    /* 所属进程 */
    struct pid *pid;                 /* 发起进程 PID */
    struct task_struct *task;        /* 发起进程 task_struct */
    struct completion done;          /* 完成通知 */

    /* 是否为异步任务 */
    bool is_async;                   /* 异步提交的任务 */
};

/* 优先级队列 */
struct ai_priority_queue {
    struct list_head queue;          /* 任务链表 */
    spinlock_t lock;                 /* 队列锁 */
    atomic_t count;                  /* 队列长度 */
    int capacity;                    /* 容量 */
};

/* 工作线程 */
struct ai_worker {
    struct task_struct *thread;      /* 内核线程 */
    int id;                          /* 线程 ID */
    struct ai_task *current_task;    /* 当前执行的任务 */
    atomic_t busy;                   /* 忙标志 */
};

/* 调度器全局状态 */
struct ai_scheduler {
    /* 优先级队列 (0=Background, 1=Low, 2=Normal, 3=High, 4=Realtime) */
    struct ai_priority_queue queues[5];

    /* 工作线程池 */
    struct ai_worker workers[AI_SCHED_THREAD_POOL];

    /* 任务 ID 生成器 */
    atomic64_t next_task_id;

    /* 统计 */
    atomic64_t total_inferences;
    atomic64_t total_tokens;
    atomic64_t total_tasks_completed;
    atomic64_t total_tasks_failed;
    atomic64_t total_tasks_timeout;

    /* 看门狗 */
    struct delayed_work watchdog_work;

    /* ========== 任务跟踪表 ========== */
    /* 用于 ai_sched_query 查找已完成/运行中的异步任务 */
    struct {
        uint64_t task_id;
        enum ai_task_status status;
        struct ai_inference_resp resp;
        bool in_use;
    } task_track[AI_TASK_TRACK_SIZE];
    spinlock_t task_track_lock;

    /* ========== 电源策略调度 ========== */
    enum ai_power_mode power_mode;          /* 当前电源策略模式 */
    uint32_t cpu_temp;                      /* 当前 CPU 温度 (毫摄氏度) */
    bool    thermal_sensor_available;       /* 温度传感器是否可用 */
    bool    throttle_active;                /* 是否正在降频 */
    struct delayed_work thermal_work;       /* 温度轮询定时器 */
    struct mutex thermal_lock;              /* 温度状态锁 */
    int     active_threads;                 /* 当前可用的工作线程数 */

    /* 状态 */
    bool running;
    struct mutex sched_lock;
};

/* 全局调度器实例 */
static struct ai_scheduler *g_sched = NULL;

/* ============================================
 * 辅助函数
 * ============================================ */

/* 获取优先级队列索引 */
static inline int priority_to_queue(enum ai_task_priority prio)
{
    if (prio > AI_PRIO_REALTIME)
        prio = AI_PRIO_REALTIME;
    if (prio < AI_PRIO_BACKGROUND)
        prio = AI_PRIO_BACKGROUND;
    return (int)prio;
}

/* 生成唯一任务 ID */
static inline uint64_t alloc_task_id(void)
{
    return (uint64_t)atomic64_inc_return(&g_sched->next_task_id);
}

/* ============================================
 * 任务跟踪表操作
 * ============================================ */

/* 向跟踪表添加任务记录 */
static void task_track_add(uint64_t task_id, enum ai_task_status status,
                            struct ai_inference_resp *resp)
{
    unsigned long flags;
    int i;

    spin_lock_irqsave(&g_sched->task_track_lock, flags);

    /* 更新已存在的记录 */
    for (i = 0; i < AI_TASK_TRACK_SIZE; i++) {
        if (g_sched->task_track[i].in_use &&
            g_sched->task_track[i].task_id == task_id) {
            g_sched->task_track[i].status = status;
            g_sched->task_track[i].resp = *resp;
            spin_unlock_irqrestore(&g_sched->task_track_lock, flags);
            return;
        }
    }

    /* 查找空槽 */
    for (i = 0; i < AI_TASK_TRACK_SIZE; i++) {
        if (!g_sched->task_track[i].in_use) {
            g_sched->task_track[i].task_id = task_id;
            g_sched->task_track[i].status = status;
            g_sched->task_track[i].resp = *resp;
            g_sched->task_track[i].in_use = true;
            spin_unlock_irqrestore(&g_sched->task_track_lock, flags);
            return;
        }
    }

    /* 表满，覆盖最早的记录 (循环覆盖) */
    {
        static unsigned int track_evict_idx = 0;
        g_sched->task_track[track_evict_idx].task_id = task_id;
        g_sched->task_track[track_evict_idx].status = status;
        g_sched->task_track[track_evict_idx].resp = *resp;
        g_sched->task_track[track_evict_idx].in_use = true;
        track_evict_idx = (track_evict_idx + 1) % AI_TASK_TRACK_SIZE;
    }

    spin_unlock_irqrestore(&g_sched->task_track_lock, flags);
}

/* 从跟踪表查询任务，查询后移除记录 */
static int task_track_query(uint64_t task_id, struct ai_inference_resp *resp)
{
    unsigned long flags;
    int i;

    spin_lock_irqsave(&g_sched->task_track_lock, flags);

    for (i = 0; i < AI_TASK_TRACK_SIZE; i++) {
        if (g_sched->task_track[i].in_use &&
            g_sched->task_track[i].task_id == task_id) {
            *resp = g_sched->task_track[i].resp;
            resp->status = g_sched->task_track[i].status;
            /* 查询后移除记录 */
            g_sched->task_track[i].in_use = false;
            spin_unlock_irqrestore(&g_sched->task_track_lock, flags);
            return 0;
        }
    }

    spin_unlock_irqrestore(&g_sched->task_track_lock, flags);
    return -AI_ERR_INVALID_PARAM;
}

/* ============================================
 * 任务队列操作
 * ============================================ */

/* 入队 */
static int enqueue_task(struct ai_task *task)
{
    int qidx = priority_to_queue(task->priority);
    struct ai_priority_queue *pq = &g_sched->queues[qidx];

    if (atomic_read(&pq->count) >= pq->capacity) {
        pr_warn_ratelimited("ainos: priority queue %d is full\n", qidx);
        return -AI_ERR_TASK_QUEUE_FULL;
    }

    task->task_id = alloc_task_id();
    task->status = AI_TASK_PENDING;
    task->enqueue_time = ktime_get();
    task->deadline = ktime_add_ms(task->enqueue_time, AI_SCHED_MAX_RUNTIME_MS);

    spin_lock(&pq->lock);
    list_add_tail(&task->node, &pq->queue);
    atomic_inc(&pq->count);
    spin_unlock(&pq->lock);

    pr_debug("ainos: task %llu enqueued to priority queue %d\n",
             task->task_id, qidx);
    return 0;
}

/* 出队 - 从最高优先级非空队列取任务 */
static struct ai_task *dequeue_task(void)
{
    struct ai_task *task = NULL;

    /* 从高到低遍历优先级 */
    for (int qidx = AI_PRIO_REALTIME; qidx >= AI_PRIO_BACKGROUND; qidx--) {
        struct ai_priority_queue *pq = &g_sched->queues[qidx];

        if (atomic_read(&pq->count) == 0)
            continue;

        spin_lock(&pq->lock);
        if (!list_empty(&pq->queue)) {
            task = list_first_entry(&pq->queue, struct ai_task, node);
            list_del_init(&task->node);
            atomic_dec(&pq->count);
            task->status = AI_TASK_RUNNING;
            task->start_time = ktime_get();
        }
        spin_unlock(&pq->lock);

        if (task)
            break;
    }

    return task;
}

/* 取消任务 */
static int cancel_task(uint64_t task_id)
{
    /* 在所有队列中查找并取消 */
    for (int qidx = 0; qidx <= AI_PRIO_REALTIME; qidx++) {
        struct ai_priority_queue *pq = &g_sched->queues[qidx];
        struct ai_task *task, *tmp;

        spin_lock(&pq->lock);
        list_for_each_entry_safe(task, tmp, &pq->queue, node) {
            if (task->task_id == task_id) {
                list_del_init(&task->node);
                atomic_dec(&pq->count);
                task->status = AI_TASK_CANCELLED;
                complete_all(&task->done);
                spin_unlock(&pq->lock);
                pr_info("ainos: task %llu cancelled\n", task_id);
                return 0;
            }
        }
        spin_unlock(&pq->lock);
    }

    return -AI_ERR_INVALID_PARAM;
}

/* ============================================
 * 工作线程
 * ============================================ */

static int ai_worker_thread(void *data)
{
    struct ai_worker *worker = (struct ai_worker *)data;
    struct ai_task *task;
    int throttle_sleep = 0;

    pr_info("ainos: worker %d started\n", worker->id);

    while (!kthread_should_stop()) {
        /* 电源策略：检查是否应该让出 CPU */
        if (g_sched && g_sched->thermal_sensor_available) {
            mutex_lock(&g_sched->thermal_lock);
            if (g_sched->power_mode >= AI_POWER_EFFICIENT) {
                /* 节能模式：减少工作线程调度频率 */
                throttle_sleep = (g_sched->power_mode == AI_POWER_EMERGENCY) ? 3 : 1;
            } else {
                throttle_sleep = 0;
            }
            mutex_unlock(&g_sched->thermal_lock);
        }

        /* 尝试获取任务 */
        task = dequeue_task();
        if (!task) {
            /* 没有任务，等待（节流模式下等待更久） */
            ssleep(throttle_sleep > 0 ? throttle_sleep : 1);
            continue;
        }

        worker->current_task = task;
        atomic_set(&worker->busy, 1);

        pr_debug("ainos: worker %d executing task %llu (priority %d)\n",
                 worker->id, task->task_id, task->priority);

        /* 模拟推理执行 */
        /* 实际运行时，这里会调用用户态 AI Runtime 进行推理 */
        {
            /* 电源策略感知的推理延迟 */
            int sleep_ms = 100;
            if (g_sched && g_sched->thermal_sensor_available) {
                mutex_lock(&g_sched->thermal_lock);
                switch (g_sched->power_mode) {
                case AI_POWER_MAX:
                    sleep_ms = 50;   /* 全速 */
                    break;
                case AI_POWER_BALANCED:
                    sleep_ms = 100;  /* 平衡 */
                    break;
                case AI_POWER_EFFICIENT:
                    sleep_ms = 200;  /* 节能 */
                    break;
                case AI_POWER_EMERGENCY:
                    sleep_ms = 400;  /* 紧急 */
                    break;
                }
                mutex_unlock(&g_sched->thermal_lock);
            }
            msleep_interruptible(sleep_ms);
        }

        /* 标记完成 */
        task->resp.status = AI_TASK_COMPLETED;
        task->resp.tokens_generated = 128;
        task->resp.inference_ms = 100;
        task->resp.total_ms = ktime_to_ms(ktime_sub(ktime_get(), task->enqueue_time));

        /* 更新统计 */
        atomic64_inc(&g_sched->total_inferences);
        atomic64_add(task->resp.tokens_generated, &g_sched->total_tokens);
        atomic64_inc(&g_sched->total_tasks_completed);

        /* 通知等待者 */
        complete_all(&task->done);

        /* 异步任务：添加到跟踪表并释放 */
        if (task->is_async) {
            task_track_add(task->task_id, AI_TASK_COMPLETED, &task->resp);
            if (task->pid)
                put_pid(task->pid);
            kfree(task);
        }

        worker->current_task = NULL;
        atomic_set(&worker->busy, 0);
    }

    pr_info("ainos: worker %d stopped\n", worker->id);
    return 0;
}

/* ============================================
 * 看门狗 - 检查超时任务
 * ============================================ */

static void watchdog_callback(struct work_struct *work)
{
    struct ai_task *task, *tmp;
    ktime_t now = ktime_get();

    if (!g_sched || !g_sched->running)
        return;

    /* 检查所有运行中的任务是否超时 */
    for (int i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        struct ai_worker *worker = &g_sched->workers[i];
        if (atomic_read(&worker->busy) && worker->current_task) {
            task = worker->current_task;
            if (ktime_after(now, task->deadline)) {
                pr_warn("ainos: task %llu timeout after %llu ms\n",
                        task->task_id,
                        ktime_to_ms(ktime_sub(now, task->start_time)));
                task->status = AI_TASK_FAILED;
                task->resp.status = AI_TASK_FAILED;
                complete_all(&task->done);
                atomic64_inc(&g_sched->total_tasks_timeout);

                /* 异步任务：添加到跟踪表并释放 */
                if (task->is_async) {
                    task_track_add(task->task_id, AI_TASK_FAILED, &task->resp);
                    if (task->pid)
                        put_pid(task->pid);
                    kfree(task);
                }

                atomic_set(&worker->busy, 0);
                worker->current_task = NULL;
            }
        }
    }

    /* 重新调度看门狗 */
    if (g_sched->running)
        schedule_delayed_work(&g_sched->watchdog_work,
                              msecs_to_jiffies(AI_SCHED_WATCHDOG_MS));
}

/* ============================================
 * 电源策略调度 - 温度监控
 * ============================================ */

/* 从 /sysfs 读取 CPU 温度 */
static int read_cpu_temperature(uint32_t *temp_milli)
{
    struct file *f;
    char buf[16];
    loff_t pos = 0;
    ssize_t ret;

    f = filp_open(AI_THERMAL_PATH, O_RDONLY, 0);
    if (IS_ERR(f))
        return -EIO;

    ret = kernel_read(f, buf, sizeof(buf) - 1, &pos);
    filp_close(f, NULL);

    if (ret <= 0)
        return -EIO;

    buf[ret] = '\0';

    if (kstrtou32(buf, 10, temp_milli) != 0)
        return -EINVAL;

    return 0;
}

/* 根据温度计算电源策略模式 */
static enum ai_power_mode calculate_power_mode(uint32_t temp_milli)
{
    if (temp_milli >= AI_TEMP_CRITICAL)
        return AI_POWER_EMERGENCY;
    if (temp_milli >= AI_TEMP_WARM_MAX)
        return AI_POWER_EFFICIENT;
    if (temp_milli >= AI_TEMP_COOL_MAX)
        return AI_POWER_BALANCED;
    return AI_POWER_MAX;
}

/* 获取电源策略状态 */
void ai_sched_get_power_status(struct ai_power_status *status)
{
    if (!g_sched || !status)
        return;

    mutex_lock(&g_sched->thermal_lock);
    status->current_mode = g_sched->power_mode;
    status->cpu_temp = g_sched->cpu_temp;
    status->cpu_temp_decicelsius = g_sched->cpu_temp / 100;
    status->recommended_threads = mode_threads[g_sched->power_mode];
    status->throttle_active = g_sched->throttle_active;
    status->sensor_available = g_sched->thermal_sensor_available;
    mutex_unlock(&g_sched->thermal_lock);
}
EXPORT_SYMBOL_GPL(ai_sched_get_power_status);

/* 手动设置电源策略模式 */
int ai_sched_set_power_mode(enum ai_power_mode mode)
{
    if (!g_sched)
        return -AI_ERR_GENERAL;

    if (mode > AI_POWER_EMERGENCY)
        return -AI_ERR_INVALID_PARAM;

    mutex_lock(&g_sched->thermal_lock);
    g_sched->power_mode = mode;
    g_sched->active_threads = mode_threads[mode];
    g_sched->throttle_active = (mode >= AI_POWER_EFFICIENT);
    mutex_unlock(&g_sched->thermal_lock);

    pr_info("ainos: power mode manually set to %d (threads=%d)\n",
            mode, g_sched->active_threads);
    return 0;
}
EXPORT_SYMBOL_GPL(ai_sched_set_power_mode);

/* 温度轮询回调 */
static void thermal_monitor_callback(struct work_struct *work)
{
    uint32_t temp_milli = 0;
    enum ai_power_mode new_mode;
    enum ai_power_mode old_mode;

    if (!g_sched || !g_sched->running)
        return;

    /* 读取温度 */
    if (read_cpu_temperature(&temp_milli) == 0) {
        mutex_lock(&g_sched->thermal_lock);
        g_sched->cpu_temp = temp_milli;
        g_sched->thermal_sensor_available = true;

        old_mode = g_sched->power_mode;
        new_mode = calculate_power_mode(temp_milli);

        if (new_mode != old_mode) {
            g_sched->power_mode = new_mode;
            g_sched->active_threads = mode_threads[new_mode];
            g_sched->throttle_active = (new_mode >= AI_POWER_EFFICIENT);

            pr_info("ainos: thermal throttle: %s -> %s (temp=%u.%03u°C)\n",
                    old_mode == AI_POWER_MAX ? "MAX" :
                    old_mode == AI_POWER_BALANCED ? "BALANCED" :
                    old_mode == AI_POWER_EFFICIENT ? "EFFICIENT" : "EMERGENCY",
                    new_mode == AI_POWER_MAX ? "MAX" :
                    new_mode == AI_POWER_BALANCED ? "BALANCED" :
                    new_mode == AI_POWER_EFFICIENT ? "EFFICIENT" : "EMERGENCY",
                    temp_milli / 1000, temp_milli % 1000);
        }
        mutex_unlock(&g_sched->thermal_lock);
    } else {
        /* 传感器失效 */
        mutex_lock(&g_sched->thermal_lock);
        if (g_sched->thermal_sensor_available) {
            pr_warn("ainos: thermal sensor lost, disabling auto-throttle\n");
            g_sched->thermal_sensor_available = false;
        }
        mutex_unlock(&g_sched->thermal_lock);
    }

    /* 重新调度温度监控 */
    if (g_sched->running)
        schedule_delayed_work(&g_sched->thermal_work,
                              msecs_to_jiffies(AI_THERMAL_POLL_MS));
}

/* ============================================
 * 公共 API
 * ============================================ */

/* 提交 AI 推理任务 */
int ai_sched_submit(struct ai_inference_req *req,
                     struct ai_inference_resp *resp)
{
    struct ai_task *task;
    int ret;

    if (!g_sched || !g_sched->running)
        return -AI_ERR_GENERAL;

    task = kzalloc(sizeof(*task), GFP_KERNEL);
    if (!task)
        return -AI_ERR_OUT_OF_MEMORY;

    /* 复制请求 */
    memcpy(&task->req, req, sizeof(*req));
    task->resp = *resp;
    task->pid = get_pid(task_task(current));
    task->task = current;
    init_completion(&task->done);

    /* 入队 */
    ret = enqueue_task(task);
    if (ret) {
        kfree(task);
        return ret;
    }

    /* 等待完成 (或异步返回) */
    wait_for_completion_interruptible(&task->done);

    /* 复制响应 */
    *resp = task->resp;

    /* 清理 */
    if (task->pid)
        put_pid(task->pid);
    kfree(task);

    return 0;
}

/* 异步提交任务 (立即返回 task_id) */
int ai_sched_submit_async(struct ai_inference_req *req,
                           uint64_t *task_id)
{
    struct ai_task *task;
    int ret;

    if (!g_sched || !g_sched->running)
        return -AI_ERR_GENERAL;

    task = kzalloc(sizeof(*task), GFP_KERNEL);
    if (!task)
        return -AI_ERR_OUT_OF_MEMORY;

    memcpy(&task->req, req, sizeof(*req));
    task->pid = get_pid(task_task(current));
    task->task = current;
    init_completion(&task->done);
    task->is_async = true;  /* 标记为异步任务 */

    ret = enqueue_task(task);
    if (ret) {
        if (task->pid)
            put_pid(task->pid);
        kfree(task);
        return ret;
    }

    *task_id = task->task_id;
    return 0;
}

/* 查询任务状态 */
int ai_sched_query(uint64_t task_id, struct ai_inference_resp *resp)
{
    struct ai_task *task;
    unsigned long flags;
    int i;

    if (!g_sched || !g_sched->running)
        return -AI_ERR_GENERAL;

    if (!resp)
        return -AI_ERR_INVALID_PARAM;

    memset(resp, 0, sizeof(*resp));

    /* 1. 检查任务跟踪表 (已完成或已失败的异步任务) */
    if (task_track_query(task_id, resp) == 0)
        return 0;

    /* 2. 检查优先级队列 (等待中的任务) */
    for (i = 0; i <= AI_PRIO_REALTIME; i++) {
        struct ai_priority_queue *pq = &g_sched->queues[i];

        if (atomic_read(&pq->count) == 0)
            continue;

        spin_lock_irqsave(&pq->lock, flags);
        list_for_each_entry(task, &pq->queue, node) {
            if (task->task_id == task_id) {
                *resp = task->resp;
                resp->status = task->status;
                resp->task_id = task->task_id;
                spin_unlock_irqrestore(&pq->lock, flags);
                return 0;
            }
        }
        spin_unlock_irqrestore(&pq->lock, flags);
    }

    /* 3. 检查工作线程 (运行中的任务) */
    for (i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        struct ai_worker *worker = &g_sched->workers[i];

        if (atomic_read(&worker->busy) && worker->current_task) {
            task = worker->current_task;
            if (task->task_id == task_id) {
                *resp = task->resp;
                resp->status = task->status;
                resp->task_id = task->task_id;
                return 0;
            }
        }
    }

    /* 4. 未找到 */
    return -AI_ERR_INVALID_PARAM;
}

/* 取消任务 */
int ai_sched_cancel(uint64_t task_id)
{
    return cancel_task(task_id);
}

/* 获取调度器状态 */
void ai_sched_get_status(struct ai_system_status *status)
{
    if (!g_sched || !status)
        return;

    memset(status, 0, sizeof(*status));

    status->tasks_pending = 0;
    for (int i = 0; i <= AI_PRIO_REALTIME; i++)
        status->tasks_pending += atomic_read(&g_sched->queues[i].count);

    status->tasks_running = 0;
    for (int i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        if (atomic_read(&g_sched->workers[i].busy))
            status->tasks_running++;
    }

    status->total_inferences = atomic64_read(&g_sched->total_inferences);
    status->total_tokens = atomic64_read(&g_sched->total_tokens);
    strncpy(status->version, "0.1.0", sizeof(status->version) - 1);
}

EXPORT_SYMBOL_GPL(ai_sched_submit);
EXPORT_SYMBOL_GPL(ai_sched_submit_async);
EXPORT_SYMBOL_GPL(ai_sched_query);
EXPORT_SYMBOL_GPL(ai_sched_cancel);
EXPORT_SYMBOL_GPL(ai_sched_get_status);

/* ============================================
 * 模块初始化/退出
 * ============================================ */

static int __init ai_scheduler_init(void)
{
    int ret = 0;
    int i;

    pr_info("ainos: AI Scheduler loading...\n");

    /* 分配全局状态 */
    g_sched = kzalloc(sizeof(*g_sched), GFP_KERNEL);
    if (!g_sched)
        return -ENOMEM;

    /* 初始化优先级队列 */
    for (i = 0; i <= AI_PRIO_REALTIME; i++) {
        INIT_LIST_HEAD(&g_sched->queues[i].queue);
        spin_lock_init(&g_sched->queues[i].lock);
        atomic_set(&g_sched->queues[i].count, 0);
        g_sched->queues[i].capacity = queue_capacity[i];
    }

    /* 初始化工作线程 */
    for (i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        g_sched->workers[i].id = i;
        atomic_set(&g_sched->workers[i].busy, 0);
        g_sched->workers[i].current_task = NULL;

        g_sched->workers[i].thread = kthread_run(ai_worker_thread,
                                                   &g_sched->workers[i],
                                                   "ainos-worker-%d", i);
        if (IS_ERR(g_sched->workers[i].thread)) {
            ret = PTR_ERR(g_sched->workers[i].thread);
            pr_err("ainos: failed to start worker %d: %d\n", i, ret);
            goto err_workers;
        }
    }

    /* 初始化统计 */
    atomic64_set(&g_sched->next_task_id, 0);
    atomic64_set(&g_sched->total_inferences, 0);
    atomic64_set(&g_sched->total_tokens, 0);
    atomic64_set(&g_sched->total_tasks_completed, 0);
    atomic64_set(&g_sched->total_tasks_failed, 0);
    atomic64_set(&g_sched->total_tasks_timeout, 0);

    /* 初始化任务跟踪表 */
    spin_lock_init(&g_sched->task_track_lock);
    memset(g_sched->task_track, 0, sizeof(g_sched->task_track));

    /* 初始化电源策略 */
    mutex_init(&g_sched->thermal_lock);
    g_sched->power_mode = AI_POWER_MAX;
    g_sched->cpu_temp = 0;
    g_sched->thermal_sensor_available = false;
    g_sched->throttle_active = false;
    g_sched->active_threads = AI_SCHED_THREAD_POOL;

    /* 初始化看门狗和温度监控 */
    mutex_init(&g_sched->sched_lock);
    INIT_DELAYED_WORK(&g_sched->watchdog_work, watchdog_callback);
    INIT_DELAYED_WORK(&g_sched->thermal_work, thermal_monitor_callback);
    g_sched->running = true;
    schedule_delayed_work(&g_sched->watchdog_work,
                          msecs_to_jiffies(AI_SCHED_WATCHDOG_MS));
    schedule_delayed_work(&g_sched->thermal_work,
                          msecs_to_jiffies(AI_THERMAL_POLL_MS));

    pr_info("ainos: AI Scheduler loaded successfully (%d workers)\n",
            AI_SCHED_THREAD_POOL);
    return 0;

err_workers:
    for (int j = 0; j < i; j++) {
        if (g_sched->workers[j].thread)
            kthread_stop(g_sched->workers[j].thread);
    }
    kfree(g_sched);
    g_sched = NULL;
    return ret;
}

static void __exit ai_scheduler_exit(void)
{
    int i;

    if (!g_sched)
        return;

    pr_info("ainos: AI Scheduler unloading...\n");

    g_sched->running = false;
    cancel_delayed_work_sync(&g_sched->watchdog_work);
    cancel_delayed_work_sync(&g_sched->thermal_work);

    /* 停止工作线程 */
    for (i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        if (g_sched->workers[i].thread) {
            kthread_stop(g_sched->workers[i].thread);
        }
    }

    /* 清理所有排队的任务 */
    for (i = 0; i <= AI_PRIO_REALTIME; i++) {
        struct ai_priority_queue *pq = &g_sched->queues[i];
        struct ai_task *task, *tmp;

        spin_lock(&pq->lock);
        list_for_each_entry_safe(task, tmp, &pq->queue, node) {
            list_del_init(&task->node);
            task->status = AI_TASK_CANCELLED;
            complete_all(&task->done);
            if (task->pid)
                put_pid(task->pid);
            kfree(task);
        }
        spin_unlock(&pq->lock);
    }

    pr_info("ainos: AI Scheduler unloaded. Stats: %llu inferences, %llu tokens\n",
            atomic64_read(&g_sched->total_inferences),
            atomic64_read(&g_sched->total_tokens));

    kfree(g_sched);
    g_sched = NULL;
}

module_init(ai_scheduler_init);
module_exit(ai_scheduler_exit);