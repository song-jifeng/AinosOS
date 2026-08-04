# Ainos OS Kernel Subsystem Architecture
# Ainos OS 内核子系统架构文档

> **Version:** 2.0.0
> **Last Updated:** 2026-08-04
> **Source Tree:** `D:/Ainos/kernel/`
> **License:** GPL-2.0 / MIT (per-module)

---

## Table of Contents / 目录

1. [AI Scheduler Design / AI 调度器设计](#1-ai-scheduler-design--ai-调度器设计)
2. [Vector Acceleration Architecture / 向量加速架构](#2-vector-acceleration-architecture--向量加速架构)
3. [Memory Management / 内存管理](#3-memory-management--内存管理)
4. [Process Management / 进程管理](#4-process-management--进程管理)
5. [Self-Healing System / 自愈系统](#5-self-healing-system--自愈系统)
6. [Hotpatch System / 热补丁系统](#6-hotpatch-system--热补丁系统)
7. [ABI Specification / ABI 规范](#7-abi-specification--abi-规范)

---

## 1. AI Scheduler Design / AI 调度器设计

### 1.1 Overview / 概述

The AI Scheduler is a kernel module that manages the lifecycle of AI inference tasks within AinosOS. It provides a multi-level priority queue scheme, power-aware worker thread scaling, watchdog supervision, and both synchronous/async task submission interfaces.

AI 调度器是一个内核模块，管理 AinosOS 中 AI 推理任务的生命周期。它提供多级优先级队列机制、电源感知的工作线程缩放、看门狗监控以及同步/异步任务提交接口。

**Source file:** `D:/Ainos/kernel/ai-scheduler-main.c`

### 1.2 Architecture / 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AI Scheduler Engine                                 │
│                         AI 调度器引擎                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Task Submission / 任务提交                          │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐  │   │
│  │  │ ai_sched_submit │  │ai_sched_submit_ │  │  ai_sched_cancel    │  │   │
│  │  │ (synchronous)   │  │async (async)    │  │  (task cancellation)│  │   │
│  │  └────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘  │   │
│  └───────────┼────────────────────┼───────────────────────┼──────────────┘   │
│              ▼                    ▼                       ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Priority Queues / 优先级队列                        │   │
│  │                                                                      │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │   │
│  │  │  REALTIME    │ │    HIGH      │ │   NORMAL     │ │    LOW       │ │   │
│  │  │  Capacity:64 │ │  Capacity:256│ │  Capacity:512│ │ Capacity:1024│ │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │   │
│  │         └────────────────┼────────────────┼────────────────┘         │   │
│  │                          ▼                ▼                          │   │
│  │                  ┌──────────────────────────────┐                     │   │
│  │                  │     BACKGROUND               │                     │   │
│  │                  │     Capacity:2048            │                     │   │
│  │                  └──────────────┬───────────────┘                     │   │
│  └─────────────────────────────────┼────────────────────────────────────┘   │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Worker Thread Pool / 工作线程池                    │   │
│  │                                                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │   │
│  │  │  Worker 0    │  │  Worker 1    │  │  Worker 2    │  │ Worker 3 │  │   │
│  │  │  ainos-wo-0  │  │  ainos-wo-1  │  │  ainos-wo-2  │  │ainos-wo-3│  │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────┬─────┘  │   │
│  │         └─────────────────┼──────────────────┼───────────────┘         │   │
│  │                           ▼                  ▼                         │   │
│  │                   Power-Aware Scaling / 电源感知缩放                    │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐              │   │
│  │  │ MAX: 4   │  │BALANCED:2│  │EFFICIENT:1│  │EMERGENCY:1│              │   │
│  │  │ <70°C    │  │ 70-85°C  │  │ 85-95°C  │  │ >95°C    │              │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Watchdog & Thermal Monitor / 看门狗与温度监控             │   │
│  │  ┌─────────────────────────────┐  ┌──────────────────────────────┐   │   │
│  │  │ Watchdog (1000ms interval)  │  │ Thermal Monitor (2000ms)     │   │   │
│  │  │ Max runtime: 60s per task   │  │ Source: /sys/class/thermal/  │   │   │
│  │  └─────────────────────────────┘  └──────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Task Tracking Table / 任务跟踪表                    │   │
│  │                  2048 entries, circular eviction                       │   │
│  │                  Used for async task completion query                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Priority Queue Design / 优先级队列设计

Five priority levels, each with a dedicated FIFO queue protected by a spinlock:

| Priority | Enum Value | Capacity | Typical Use Case |
|----------|-----------|----------|------------------|
| REALTIME | `AI_PRIO_REALTIME` (4) | 64 | System services, critical AI ops |
| HIGH     | `AI_PRIO_HIGH` (3)      | 256 | User-facing inference |
| NORMAL   | `AI_PRIO_NORMAL` (2)    | 512 | Standard batch inference |
| LOW      | `AI_PRIO_LOW` (1)       | 1024 | Background preprocessing |
| BACKGROUND | `AI_PRIO_BACKGROUND` (0) | 2048 | Offline analysis, data prep |

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 61-68 */
/* 每优先级队列容量 */
static const int queue_capacity[] = {
    [AI_PRIO_BACKGROUND] = 2048,
    [AI_PRIO_LOW]        = 1024,
    [AI_PRIO_NORMAL]     = 512,
    [AI_PRIO_HIGH]       = 256,
    [AI_PRIO_REALTIME]   = 64,
};
```

Dequeue always selects from the highest priority non-empty queue. This is a strict priority scheme with no aging -- background tasks may starve under sustained high-priority load.

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 291-317 */
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
```

### 1.4 Task States / 任务状态

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 49-55 */
enum ai_task_status {
    AI_TASK_PENDING    = 0,   /* 排队中 / Waiting in queue */
    AI_TASK_RUNNING    = 1,   /* 执行中 / Being executed */
    AI_TASK_COMPLETED  = 2,   /* 完成 / Completed successfully */
    AI_TASK_FAILED     = 3,   /* 失败 / Failed */
    AI_TASK_CANCELLED  = 4,   /* 已取消 / Cancelled by user */
};
```

### 1.5 Worker Threads / 工作线程

The scheduler maintains a pool of 4 worker threads by default. Each worker is a kernel thread (`ainos-worker-%d`) that loops:

1. **Dequeue** a task from the highest-priority non-empty queue
2. **Execute** the task (simulated with a power-aware sleep delay)
3. **Complete** the task, updating statistics and notifying waiters
4. **Async path**: completed async tasks are stored in the task tracking table and freed

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 349-438 */
static int ai_worker_thread(void *data)
{
    struct ai_worker *worker = (struct ai_worker *)data;
    struct ai_task *task;
    // ...

    while (!kthread_should_stop()) {
        /* 电源策略：检查是否应该让出 CPU */
        if (g_sched && g_sched->thermal_sensor_available) {
            mutex_lock(&g_sched->thermal_lock);
            if (g_sched->power_mode >= AI_POWER_EFFICIENT) {
                throttle_sleep = (g_sched->power_mode == AI_POWER_EMERGENCY) ? 3 : 1;
            } else {
                throttle_sleep = 0;
            }
            mutex_unlock(&g_sched->thermal_lock);
        }

        task = dequeue_task();
        if (!task) {
            ssleep(throttle_sleep > 0 ? throttle_sleep : 1);
            continue;
        }

        worker->current_task = task;
        atomic_set(&worker->busy, 1);
        // ... execute task with power-aware delay ...
        complete_all(&task->done);

        if (task->is_async) {
            task_track_add(task->task_id, AI_TASK_COMPLETED, &task->resp);
            kfree(task);
        }

        worker->current_task = NULL;
        atomic_set(&worker->busy, 0);
    }
    return 0;
}
```

### 1.6 Power-Aware Thermal Scaling / 电源感知温度缩放

The scheduler monitors CPU temperature via `/sys/class/thermal/thermal_zone0/temp` and dynamically adjusts the number of active worker threads:

| Thermal Zone | Mode | Active Threads | Inference Delay |
|-------------|------|---------------|-----------------|
| < 70°C      | MAX (AI_POWER_MAX) | 4 | 50ms |
| 70-85°C     | BALANCED (AI_POWER_BALANCED) | 2 | 100ms |
| 85-95°C     | EFFICIENT (AI_POWER_EFFICIENT) | 1 | 200ms |
| > 95°C      | EMERGENCY (AI_POWER_EMERGENCY) | 1 | 400ms |

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 46-59 */
/* 各模式线程数 */
static const int mode_threads[] = {
    [AI_POWER_MAX]       = 4,  /* 全速 */
    [AI_POWER_BALANCED]  = 2,  /* 平衡 */
    [AI_POWER_EFFICIENT] = 1,  /* 节能 */
    [AI_POWER_EMERGENCY] = 1,  /* 紧急 */
};
```

### 1.7 Watchdog / 看门狗

A delayed work item fires every 1000ms to check for hung tasks. Any task exceeding the 60-second maximum runtime is marked as FAILED and its resources are released.

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 444-484 */
static void watchdog_callback(struct work_struct *work)
{
    ktime_t now = ktime_get();
    // ...
    for (int i = 0; i < AI_SCHED_THREAD_POOL; i++) {
        struct ai_worker *worker = &g_sched->workers[i];
        if (atomic_read(&worker->busy) && worker->current_task) {
            task = worker->current_task;
            if (ktime_after(now, task->deadline)) {
                pr_warn("ainos: task %llu timeout after %llu ms\n",
                        task->task_id,
                        ktime_to_ms(ktime_sub(now, task->start_time)));
                task->status = AI_TASK_FAILED;
                complete_all(&task->done);
                atomic64_inc(&g_sched->total_tasks_timeout);
                // ... cleanup ...
            }
        }
    }
    schedule_delayed_work(&g_sched->watchdog_work,
                          msecs_to_jiffies(AI_SCHED_WATCHDOG_MS));
}
```

### 1.8 Task Tracking Table / 任务跟踪表

The tracking table stores completed async task results for later retrieval via `ai_sched_query()`. It has 2048 entries with circular eviction when full.

```c
/* From D:/Ainos/kernel/ai-scheduler-main.c, lines 192-258 */
static void task_track_add(uint64_t task_id, enum ai_task_status status,
                            struct ai_inference_resp *resp)
{
    // ... find existing or empty slot, or evict oldest ...
    g_sched->task_track[i].task_id = task_id;
    g_sched->task_track[i].status = status;
    g_sched->task_track[i].resp = *resp;
    g_sched->task_track[i].in_use = true;
}
```

### 1.9 Public API / 公共 API

| Function | Purpose | Source Reference |
|----------|---------|-----------------|
| `ai_sched_submit()` | Synchronous inference submission | `ai-scheduler-main.c:621-660` |
| `ai_sched_submit_async()` | Async submission, returns task_id | `ai-scheduler-main.c:663-692` |
| `ai_sched_query()` | Query async task status | `ai-scheduler-main.c:695-750` |
| `ai_sched_cancel()` | Cancel a pending task | `ai-scheduler-main.c:753-756` |
| `ai_sched_get_status()` | Get scheduler statistics | `ai-scheduler-main.c:759-779` |
| `ai_sched_get_power_status()` | Get current power/thermal status | `ai-scheduler-main.c:529-543` |
| `ai_sched_set_power_mode()` | Manually override power mode | `ai-scheduler-main.c:546-564` |

---

## 2. Vector Acceleration Architecture / 向量加速架构

### 2.1 Overview / 概述

The Vector Acceleration module provides runtime CPU feature detection and automatic selection of the optimal SIMD implementation for matrix multiplication, dot product, quantization, and dequantization operations. It supports both x86 (AVX2, AVX-512, AMX) and ARM64 (NEON, SVE, SVE2) architectures.

向量加速模块提供运行时 CPU 特性检测和最优 SIMD 实现的自动选择，用于矩阵乘法、点积、量化和反量化操作。支持 x86（AVX2、AVX-512、AMX）和 ARM64（NEON、SVE、SVE2）架构。

**Source file:** `D:/Ainos/kernel/ai-vector-accel-main.c`

### 2.2 Architecture / 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Vector Acceleration Engine                              │
│                      向量加速引擎                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    CPU Feature Detection / CPU 特性检测               │   │
│  │                                                                      │   │
│  │  ┌───────────────────────┐  ┌───────────────────────────────────┐   │   │
│  │  │       x86             │  │          ARM64                    │   │   │
│  │  │  ┌─────────────────┐  │  │  ┌─────────────────────────────┐  │   │   │
│  │  │  │ SSSE3           │  │  │  │ NEON (always available)    │  │   │   │
│  │  │  │ F16C            │  │  │  │ SVE (scalable vectors)     │  │   │   │
│  │  │  │ AVX2 (256-bit)  │  │  │  │ SVE2 + I8MM               │  │   │   │
│  │  │  │ AVX-512 (512bit)│  │  │  └─────────────────────────────┘  │   │   │
│  │  │  │ AVX-512 VNNI    │  │  └───────────────────────────────────┘   │   │
│  │  │  │ AMX (TILE)      │  │                                           │   │
│  │  │  │ AMX-BF16        │  │                                           │   │
│  │  │  └─────────────────┘  │                                           │   │
│  │  └──────────────┬────────┘  └──────────────────────┬────────────────┘   │
│  └─────────────────┼──────────────────────────────────┼────────────────────┘
│                    ▼                                  ▼                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Function Pointer Dispatch Table / 函数指针调度表        │   │
│  │                                                                      │   │
│  │  struct ai_vector_ops {                                              │   │
│  │      matmul_fp32_t     matmul_fp32;    /* SGEMM: C = A * B */      │   │
│  │      dot_product_t     dot_product;    /* Σ a[i] * b[i] */          │   │
│  │      quantize_t        quantize_fp32_to_q8;  /* FP32 -> INT8 */     │   │
│  │      quantize_t        quantize_fp32_to_q4;  /* FP32 -> INT4 */     │   │
│  │      dequantize_t      dequantize_q8_to_fp32; /* INT8 -> FP32 */   │   │
│  │      dequantize_t      dequantize_q4_to_fp32; /* INT4 -> FP32 */   │   │
│  │      const char       *name;                 /* Implementation name*/│   │
│  │      int               vector_size;           /* Vector width bytes */│   │
│  │  };                                                                  │   │
│  │                                                                      │   │
│  │  static struct ai_vector_ops vector_ops = { .matmul_fp32 = generic,  │   │
│  │      .dot_product = generic, ... };                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Implementation Selection / 实现选择                      │   │
│  │                                                                      │   │
│  │  Priority: AMX > AVX-512 > AVX2 > SVE2 > SVE > NEON > generic       │   │
│  │                                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │  AMX     │  │ AVX-512  │  │  AVX2    │  │ Generic  │            │   │
│  │  │ amx_impl │  │avx512_imp│  │avx2_impl │  │(fallback)│            │   │
│  │  │ .c       │  │ l.c      │  │ .c       │  │          │            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  │                                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                           │   │
│  │  │  SVE2    │  │   SVE    │  │  NEON    │                           │   │
│  │  │ sve_impl │  │ sve_impl │  │neon_impl │                           │   │
│  │  │ .c       │  │ .c       │  │ .c       │                           │   │
│  │  └──────────┘  └──────────┘  └──────────┘                           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                  Verification & Benchmark / 验证与基准测试             │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────┐  ┌──────────────────────────────┐   │   │
│  │  │ Correctness Verification  │  │ Init Benchmark (256x256)     │   │   │
│  │  │ • Dot product comparison  │  │ • matmul_fp32 cycles         │   │   │
│  │  │ • Matmul (8x8) comparison │  │ • dot_product cycles         │   │   │
│  │  │ • Quantize round-trip     │  │ • Full suite (optional)      │   │   │
│  │  └────────────────────────────┘  └──────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Public API / 公共 API                              │   │
│  │  ai_vector_matmul_fp32() | ai_vector_dot_product() |                │   │
│  │  ai_vector_get_ops() | ai_vector_accel_type() |                    │   │
│  │  ai_vector_has_feature() | ai_vector_has_simd()                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 CPU Feature Detection / CPU 特性检测

At module init, the kernel queries CPU capabilities using architecture-specific APIs:

```c
/* From D:/Ainos/kernel/ai-vector-accel-main.c, lines 48-76 */
#ifdef CONFIG_X86
static void detect_cpu_features(void)
{
    has_avx2 = boot_cpu_has(X86_FEATURE_AVX2);
    has_avx512 = boot_cpu_has(X86_FEATURE_AVX512F);
    has_avx512_vnni = boot_cpu_has(X86_FEATURE_AVX512_VNNI);
    has_amx = boot_cpu_has(X86_FEATURE_AMX_TILE);
    has_amx_bf16 = boot_cpu_has(X86_FEATURE_AMX_BF16);
    has_f16c = boot_cpu_has(X86_FEATURE_F16C);
    has_ssse3 = boot_cpu_has(X86_FEATURE_SSSE3);
}
#elif defined(CONFIG_ARM64)
static void detect_cpu_features(void)
{
    has_neon = 1; /* ARM64 始终有 NEON */
    has_sve = system_supports_sve();
    has_sve2 = system_supports_sve2();
    has_i8mm = system_capabilities_finalized() &&
               cpus_have_cap(ARM64_HAS_I8MM);
}
#endif
```

### 2.4 Function Pointer Dispatch / 函数指针调度

The core dispatch mechanism uses a struct of function pointers. At module initialization, `select_best_implementation()` iterates through priority-ordered implementations and assigns the best available:

```c
/* From D:/Ainos/kernel/ai-vector-accel-main.c, lines 195-286 */
static void select_best_implementation(void)
{
#ifdef CONFIG_X86
    if (has_amx && has_amx_bf16 && x86_amx_ops) {
        vector_ops = *x86_amx_ops;  /* AMX: highest priority */
        return;
    }
    if (has_avx512 && x86_avx512_ops) {
        vector_ops = *x86_avx512_ops;  /* AVX-512 */
        return;
    }
    if (has_avx2 && x86_avx2_ops) {
        vector_ops = *x86_avx2_ops;  /* AVX2 */
        return;
    }
#elif defined(CONFIG_ARM64)
    if (has_sve2 && arm64_sve_ops) { ... }  /* SVE2 */
    if (has_sve && arm64_sve_ops) { ... }   /* SVE */
    if (has_neon && arm64_neon_ops) { ... } /* NEON */
#endif
    /* Fallback: keep generic */
}
```

### 2.5 Architecture-Specific Implementations / 架构特定实现

**x86 implementations:**

| Implementation | File | Vector Width | Features Required |
|---------------|------|-------------|------------------|
| Generic (fallback) | `ai-vector-accel-main.c` | Scalar | None |
| AVX2 | `arch/x86/avx2_impl.c` | 32 bytes (8 floats) | AVX2 |
| AVX-512 | `arch/x86/avx512_impl.c` | 64 bytes (16 floats) | AVX-512F |
| AMX | `arch/x86/amx_impl.c` | TILE (1KB) | AMX, AMX-BF16 |

**ARM64 implementations:**

| Implementation | File | Vector Width | Features Required |
|---------------|------|-------------|------------------|
| NEON | `arch/arm64/neon_impl.c` | 16 bytes (4 floats) | Always on ARM64 |
| SVE | `arch/arm64/sve_impl.c` | Scalable (128-2048 bits) | SVE |
| SVE2 | `arch/arm64/sve_impl.c` | Scalable | SVE2, I8MM |

### 2.6 SIMD Ops Descriptor / SIMD 操作描述符

```c
/* From D:/Ainos/kernel/arch/x86/simd_impl.h, lines 27-36 */
struct simd_ops {
    matmul_fp32_fn_t matmul_fp32;
    dot_product_fn_t dot_product;
    quantize_fn_t quantize_fp32_to_q8;
    quantize_fn_t quantize_fp32_to_q4;
    dequantize_fn_t dequantize_q8_to_fp32;
    dequantize_fn_t dequantize_q4_to_fp32;
    const char *name;
    int vector_size;   /* vector register width in bytes */
};
```

### 2.7 Generic Fallback Implementation / 通用回退实现

When no SIMD is available, the module falls back to scalar C implementations:

```c
/* From D:/Ainos/kernel/ai-vector-accel-main.c, lines 102-160 */
static void matmul_fp32_generic(int m, int n, int k,
                                 const float *a, const float *b, float *c)
{
    for (int i = 0; i < m; i++) {
        for (int j = 0; j < n; j++) {
            float sum = 0.0f;
            for (int p = 0; p < k; p++) {
                sum += a[i * k + p] * b[p * n + j];
            }
            c[i * n + j] = sum;
        }
    }
}

static float dot_product_generic(int n, const float *a, const float *b)
{
    float sum = 0.0f;
    for (int i = 0; i < n; i++)
        sum += a[i] * b[i];
    return sum;
}
```

### 2.8 Init-Time Benchmark / 初始化基准测试

At module load, the module runs a quick benchmark to verify the selected implementation and measure performance. The benchmark sizes are `{64, 128, 256, 512, 1024, 2048}` (from `D:/Ainos/kernel/arch/x86/simd_benchmark.c`).

```c
/* From D:/Ainos/kernel/ai-vector-accel-main.c, lines 515-562 */
static void run_init_benchmark(void)
{
    int test_size = 256;
    int iters = 5;
    // ... allocate test data ...
    t_start = __arch_get_hw_counter(0);
    for (i = 0; i < iters; i++)
        vector_ops.matmul_fp32(n, n, n, a, b, c);
    t_end = __arch_get_hw_counter(0);

    pr_info("ainos: Init benchmark: matmul %dx%d (%s) = %llu cycles\n",
            n, n, vector_ops.name, (t_end - t_start) / iters);
}
```

### 2.9 Runtime API / 运行时 API

| Function | Purpose | Returns |
|----------|---------|---------|
| `ai_vector_get_ops()` | Get the ops dispatch table | `struct ai_vector_ops *` |
| `ai_vector_matmul_fp32()` | Matrix multiply (SGEMM) | void |
| `ai_vector_dot_product()` | Vector dot product | float |
| `ai_vector_accel_type()` | Current accelerator name | `"generic"`, `"avx2"`, `"avx512"`, `"amx"`, `"neon"`, `"sve"` |
| `ai_vector_accel_width()` | Vector register width (bytes) | int (0 = scalar) |
| `ai_vector_has_simd()` | Whether SIMD is active | bool |
| `ai_vector_has_feature()` | Check specific CPU feature | int (0/1) |

### 2.10 Sysfs Interface / Sysfs 接口

The vector accelerator exposes information via the sysfs interface at `/sys/class/ainos/vector` (from `D:/Ainos/kernel/arch/ai-vector-sysfs.c`):

```
/sys/class/ainos/vector/
├── accel_type        # Current accelerator type name
├── accel_width       # Vector register width in bytes
├── has_simd          # 1 if SIMD is active, 0 otherwise
└── features/         # Per-feature availability
    ├── avx2          # 1 if AVX2 available
    ├── avx512        # 1 if AVX-512 available
    ├── amx           # 1 if AMX available
    └── ...
```

---

## 3. Memory Management / 内存管理

### 3.1 Overview / 概述

AinosOS implements an intelligent memory management subsystem centered around AI tmpfs -- a VFS-based filesystem that provides intelligent caching, hot/warm/cold classification, and memory-pressure-aware eviction optimized for AI workloads.

AinosOS 实现了一个以 AI tmpfs 为中心的智能内存管理子系统 -- 一个基于 VFS 的文件系统，提供智能缓存、热/温/冷数据分类和内存压力感知驱逐，针对 AI 工作负载进行了优化。

**Source files:** `D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.c`, `D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.h`

### 3.2 Architecture / 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      AI tmpfs Intelligent Filesystem                         │
│                      AI tmpfs 智能文件系统                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    VFS Layer / VFS 层                                 │   │
│  │  mount -t ai_tmpfs none /mnt/ai-tmpfs                                 │   │
│  │  Operations: read, write, open, release, iterate, stat                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Access Tracking / 访问跟踪                          │   │
│  │                                                                      │   │
│  │  Each read/write automatically records:                              │   │
│  │  • Access count (atomic increment)                                   │   │
│  │  • Last access timestamp                                             │   │
│  │  • Access frequency (per-minute)                                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Hot/Warm/Cold Classification / 热/温/冷分类              │   │
│  │                                                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │   │
│  │  │    HOT       │  │    WARM      │  │    COLD      │               │   │
│  │  │ access ≥ 5   │  │ access ≥ 2   │  │  other       │               │   │
│  │  │ freq ≥ 10/min│  │              │  │              │               │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘               │   │
│  │                                                                      │   │
│  │  Classification timer fires every 60 seconds                         │   │
│  │  Adaptive thresholds adjust based on workload patterns               │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              LRU List + Shrinker / LRU 列表 + Shrinker                │   │
│  │                                                                      │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  LRU Head (evict first) ← COLD ← WARM ← HOT → LRU Tail        │  │   │
│  │  │                        (last evicted)                          │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                      │   │
│  │  shrinker_callback() registered with Linux MM shrinker framework     │   │
│  │  • Triggered under memory pressure                                   │   │
│  │  • Evicts cold data first, then warm, then hot (last resort)         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 AI tmpfs Configuration / AI tmpfs 配置

```c
/* From D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.h, lines 15-28 */
/* 热数据阈值 */
#define AI_TMPFS_HOT_ACCESS_MIN    5    /* 最少访问次数 */
#define AI_TMPFS_HOT_FREQ_MIN      10   /* 每分钟最少访问次数 */
#define AI_TMPFS_WARM_ACCESS_MIN   2    /* 温数据最少访问次数 */

/* 文件大小限制 */
#define AI_TMPFS_MAX_FILE_SIZE     (16UL * 1024 * 1024)  /* 16MB */
#define AI_TMPFS_MAX_FILES         4096
#define AI_TMPFS_MAX_NAME_LEN      256

/* 冷数据清理间隔 (秒) */
#define AI_TMPFS_CLEAN_INTERVAL    30
```

### 3.4 Model Cache / 模型缓存

The model cache is allocated within AI tmpfs with a default size of 4096 MB, configurable at mount time. This cache stores loaded AI model weights and is managed by the VFS page cache, benefiting from the hot/warm/cold classification.

**Key parameters:**
- Default cache size: 4096 MB
- Maximum file size: 16 MB (per file)
- Maximum files: 4096

### 3.5 Semantic Cache / 语义缓存

The semantic cache uses an LRU (Least Recently Used) strategy with 1000 entries. It stores recent inference results keyed by their embedding vectors, allowing repeated queries to be served from cache without re-running inference.

**Integration points:**
- Cache hit: Returns cached result immediately
- Cache miss: Performs inference, stores result in LRU
- LRU eviction: Oldest entry removed when cache is full
- Memory pressure: Semantic cache entries are reclaimable under memory pressure

### 3.6 Memory Pressure Monitoring / 内存压力监控

Memory pressure is monitored through:
1. **Linux MM shrinker framework**: The AI tmpfs registers a shrinker that is called under memory pressure
2. **Self-healing integration**: The self-healing module monitors memory pressure via `si_mem_available()` and triggers recovery actions when free memory drops below thresholds
3. **KV-cache management**: During inference, the KV-cache usage is tracked and can trigger early eviction of stale context entries

### 3.7 KV-Cache Management / KV-Cache 管理

The KV-cache stores key-value pairs from inference sessions for context management:

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 128-137 */
#define AI_CONTEXT_KEY_MAX 128
#define AI_CONTEXT_VAL_MAX 65536

struct ai_context_entry {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    char __user *value;
    uint64_t value_len;
    uint64_t value_capacity;
};
```

Context entries are stored via system calls `sys_ai_context_store` (455) and retrieved via `sys_ai_context_retrieve` (456). The cache supports TTL-based expiration and can be reclaimed under memory pressure.

### 3.8 AI tmpfs Statistics / AI tmpfs 统计

```c
/* From D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.h, lines 32-49 */
struct ai_tmpfs_stats {
    __u64  files_total;
    __u64  files_hot;
    __u64  files_warm;
    __u64  files_cold;
    __u64  bytes_total;
    __u64  bytes_hot;
    __u64  bytes_warm;
    __u64  bytes_cold;
    __u64  reads_total;
    __u64  writes_total;
    __u64  evictions_total;
    __u64  evictions_hot;
    __u64  hits_hot;
    __u64  hits_cold;
    __u64  shrinker_calls;
    __u64  uptime_seconds;
};
```

---

## 4. Process Management / 进程管理

### 4.1 Overview / 概述

AinosOS process management encompasses two subsystems: **AI KILL** -- an intelligent process scoring and termination engine, and **AI-proc** -- a `/proc/ai` virtual filesystem for userspace AI communication.

AinosOS 进程管理包含两个子系统：**AI KILL** -- 智能进程评分和终止引擎，以及 **AI-proc** -- 一个用于用户空间 AI 通信的 `/proc/ai` 虚拟文件系统。

**Source files:**
- `D:/Ainos/kernel/ai-kill/ai_kill.c` (process scoring and killing)
- `D:/Ainos/kernel/ai-kill/ai_kill.h` (data structures and API)
- `D:/Ainos/kernel/ai-proc/proc_ai.c` (/proc/ai filesystem)
- `D:/Ainos/kernel/ai-proc/ai-proc-bridge.c` (userspace bridge daemon)

### 4.2 AI KILL Architecture / AI KILL 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      AI KILL Intelligent Process Manager                     │
│                      AI KILL 智能进程管理器                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Process Scanner (Timer + Workqueue) / 进程扫描器          │   │
│  │  Interval: 3000ms (configurable via /proc/ai-kill/config)             │   │
│  │  Scans all processes, skips kernel threads, init, and whitelist       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              7-Dimension Scoring Engine / 7 维度评分引擎              │   │
│  │                                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │   │
│  │  │  CPU     │  │   MEM    │  │    IO    │  │   NET    │            │   │
│  │  │ (Weight  │  │ (Weight  │  │ (Weight  │  │ (Weight  │            │   │
│  │  │  20)     │  │  25)     │  │  15)     │  │  10)     │            │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │   │
│  │                                                                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                           │   │
│  │  │   AGE    │  │CRITICALITY│  │   LEAK   │                           │   │
│  │  │ (Weight  │  │ (Weight  │  │ (Weight  │                           │   │
│  │  │  10)     │  │  20)     │  │  20)     │                           │   │
│  │  │          │  │ (NEGATIVE)│  │          │                           │   │
│  │  └──────────┘  └──────────┘  └──────────┘                           │   │
│  │                                                                      │   │
│  │  Total = max(0, Σ(weight_i * score_i) / Σ(weight_i))                │   │
│  │  CRITICALITY contributes negatively (protects important processes)  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Thresholds & Action Selection / 阈值与动作选择           │   │
│  │                                                                      │   │
│  │  Score 0-39:  NONE  (no action)                                     │   │
│  │  Score 40-59: WARN  (log warning)                                   │   │
│  │  Score 60-79: TERM  (send SIGTERM)                                  │   │
│  │  Score 80-89: KILL  (send SIGKILL)                                  │   │
│  │  Score 90+:   GROUP (kill entire process group)                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Rate Limiter & Whitelist / 速率限制与白名单              │   │
│  │                                                                      │   │
│  │  • Rate limit: 10000ms between kills, 10 kills/minute max           │   │
│  │  • Whitelist: init, systemd, sshd, cron, etc. (always protected)    │   │
│  │  • Whitelist hits tracked in statistics                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Execution & History / 执行与历史                          │   │
│  │  • SIGTERM → 1000ms wait → SIGKILL (graceful kill)                  │   │
│  • kill_pgrp() for group kills                                           │   │
│  • 128-entry ring buffer kill history                                   │   │
│  • Behavior tracking table (256 entries, 3 samples each)                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Scoring Formula / 评分公式

The total score is calculated with a weighted formula where CRITICALITY contributes negatively (protecting important processes):

```
total = max(0, Σ(weight_i * score_i) / Σ(weight_i))

Where:
  CPU(20) * score_cpu + MEM(25) * score_mem + IO(15) * score_io
  + NET(10) * score_net + AGE(10) * score_age
  - CRITICALITY(20) * score_criticality
  + LEAK(20) * score_leak
```

```c
/* From D:/Ainos/kernel/ai-kill/ai_kill.c, lines 778-828 */
static unsigned int calc_total_score(const struct ai_kill_score *score)
{
    unsigned int total_weight = 0;
    int weighted_sum = 0;  /* 有符号, 因为 CRITICALITY 贡献为负 */
    unsigned int normalized[AI_KILL_DIM_COUNT];

    /* Step 1: 各维度归一化到 0-100 */
    for (int i = 0; i < AI_KILL_DIM_COUNT; i++)
        normalized[i] = min(score->dims[i], 100u);

    /* Step 2: 资源维度约束检查 */
    {
        unsigned int sum = normalized[AI_KILL_DIM_CPU]
                         + normalized[AI_KILL_DIM_MEM]
                         + normalized[AI_KILL_DIM_IO];
        if (sum > 100) {
            unsigned int scale = 100;
            normalized[AI_KILL_DIM_CPU] = normalized[AI_KILL_DIM_CPU] * scale / sum;
            normalized[AI_KILL_DIM_MEM] = normalized[AI_KILL_DIM_MEM] * scale / sum;
            normalized[AI_KILL_DIM_IO]  = normalized[AI_KILL_DIM_IO]  * scale / sum;
        }
    }

    /* Step 3: 应用权重 */
    for (int i = 0; i < AI_KILL_DIM_COUNT; i++) {
        unsigned int w = g_ai_kill.config.weights[i];
        if (i == AI_KILL_DIM_CRITICALITY) {
            weighted_sum -= (int)(normalized[i] * w);
        } else {
            weighted_sum += (int)(normalized[i] * w);
        }
        total_weight += w;
    }

    if (total_weight == 0) return 0;
    if (weighted_sum < 0) return 0;
    unsigned int total = (unsigned int)weighted_sum / total_weight;
    return min(total, 100u);
}
```

### 4.4 Scoring Dimensions / 评分维度

| Dimension | Weight | Description |
|-----------|--------|-------------|
| CPU (index 0) | 20 | CPU usage percentage (0-100) |
| MEM (index 1) | 25 | RSS + swap usage, absolute and relative |
| IO (index 2) | 15 | Total IO bytes read/written |
| NET (index 3) | 10 | File descriptor count (socket proxy) |
| AGE (index 4) | 10 | Process age (younger = higher score) |
| CRITICALITY (index 5) | 20 (NEGATIVE) | Importance of process (higher = more protected) |
| LEAK (index 6) | 20 | Memory leak detection (RSS growth trend) |

### 4.5 Memory Leak Detection / 内存泄漏检测

The leak detector uses a 3-sample moving average with a baseline tracking mechanism:

```c
/* From D:/Ainos/kernel/ai-kill/ai_kill.c, lines 502-552 */
static int detect_memory_leak(const struct behavior_entry *entry)
{
    /* Calculate 3-sample moving average */
    moving_avg = 0;
    count = min(entry->sample_count, BEHAVIOR_SAMPLES);
    for (i = 0; i < count; i++)
        moving_avg += entry->samples[i].rss_bytes;
    moving_avg /= count;

    /* Condition 1: RSS exceeds moving average by 20% */
    /* Condition 2: Growth from baseline > 1MB */
    /* Return leak score (0-100) based on growth percentage */
}
```

### 4.6 Whitelist Protection / 白名单保护

The whitelist protects critical system processes from being killed:

```c
/* From D:/Ainos/kernel/ai-kill/ai_kill.c, lines 240-263 */
static const char * const default_protected_processes[] = {
    "init", "systemd", "sshd", "cron", "rsyslogd",
    "dbus-daemon", "NetworkManager", "login", "getty",
    "agetty", "auditd", "polkitd", "udevd",
    "systemd-journald", "systemd-logind", "systemd-udevd",
    "systemd-resolved", "systemd-timesyncd",
    "kthreadd", "rcu_sched", "watchdogd",
    NULL  /* sentinel */
};
```

### 4.7 AI-proc Filesystem / AI-proc 文件系统

The `/proc/ai` virtual filesystem provides a bridge between userspace and the AI kernel subsystem. It is implemented as a misc device (`/dev/ainos-proc`) with IOCTL-based communication.

**Source:** `D:/Ainos/kernel/ai-proc/proc_ai.c`

**Architecture:**
```
┌──────────────┐    write/read     ┌──────────────────┐    IOCTL    ┌──────────────┐
│  User App    │  ──────────────>  │  /proc/ai/*      │  ────────>  │  ai-proc-bridge
│  (echo/cat)  │  <──────────────  │  (kernel VFS)    │  <────────  │  (userspace)  │
└──────────────┘                   └──────────────────┘             └──────┬───────┘
                                                                           │ TCP
                                                                           │ 9500
                                                                           ▼
                                                                    ┌──────────────┐
                                                                    │  ai-daemon   │
                                                                    └──────────────┘
```

**Proc files:**

| File | ID | Purpose |
|------|----|---------|
| `/proc/ai/status` | 0 | AI subsystem status |
| `/proc/ai/infer` | 1 | Submit inference requests |
| `/proc/ai/embed` | 2 | Text embedding |
| `/proc/ai/chat` | 3 | Chat completion |
| `/proc/ai/models` | 4 | Model management |
| `/proc/ai/config` | 5 | Configuration |
| `/proc/ai/stats` | 6 | Statistics |

**Bridge daemon:** `D:/Ainos/kernel/ai-proc/ai-proc-bridge.c`

The bridge runs in userspace and connects to `ai-daemon` on TCP port 9500 (`127.0.0.1:9500`). It:

1. Blocks waiting for kernel AI requests via `AI_PROC_GET_REQUEST` IOCTL
2. Forwards requests to ai-daemon over TCP
3. Writes responses back to kernel via `AI_PROC_SEND_RESPONSE` IOCTL
4. Handles retries (max 3), timeouts (30s), and reconnection (2s delay)

### 4.8 Process Priority Boosting / 进程优先级提升

The AI scheduler can boost the priority of processes associated with AI tasks. This is done through integration with the AI KILL scoring system (AI tasks get lower CRITICALITY scores, making them less likely to be killed) and through the scheduler's priority queue (AI inference tasks can be submitted at HIGH priority).

---

## 5. Self-Healing System / 自愈系统

### 5.1 Overview / 概述

The Self-Healing system is a kernel module that provides proactive monitoring, anomaly detection, and graduated recovery for AinosOS. It uses a combination of preventive monitoring (timer + workqueue) and reactive detection (notifier chains) to maintain system health.

自愈系统是一个内核模块，为 AinosOS 提供主动监控、异常检测和渐变恢复。它结合了预防性监控（定时器 + 工作队列）和反应式检测（通知器链）来维护系统健康。

**Source files:** `D:/Ainos/kernel/ai-self-heal/self_heal.c`, `D:/Ainos/kernel/ai-self-heal/self_heal.h`

### 5.2 Architecture / 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Self-Healing Engine / 自愈引擎                           │
│                      Version 2.0.0                                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Preventive Monitoring / 预防性监控                        │   │
│  │  Timer (10s) ──> Workqueue (self-heal-mon) ──> heal_monitor_work()   │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  Memory Pressure Check                                      │   │   │
│  │  │  • MemAvailable < 5% total → CRITICAL event                 │   │   │
│  │  │  • MemAvailable < 10% total → WARNING event                 │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  Zombie Process Check                                        │   │   │
│  │  │  • Zombie count >= 50 → CRITICAL event                       │   │   │
│  │  │  • Zombie count >= 20 → WARNING event                        │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  System Load Check                                           │   │   │
│  │  │  • Load average > 8x CPUs → CRITICAL event                   │   │   │
│  │  │  • Load average > 4x CPUs → WARNING event                    │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Reactive Detection / 反应式检测                          │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  Panic Notifier Chain                                        │   │   │
│  │  │  Registered with atomic_notifier_chain_register()            │   │   │
│  │  │  Priority: INT_MAX (highest priority)                        │   │   │
│  │  │  • Records panic events in ring buffer (atomic context)      │   │   │
│  │  │  • Uses spin_trylock to avoid deadlock in panic context      │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  External Module API                                         │   │   │
│  │  │  self_heal_report_event() / self_heal_report_event_level()  │   │   │
│  │  │  self_heal_force_recovery()                                   │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Policy Engine / 策略引擎                                  │   │
│  │                                                                      │   │
│  │  heal_process_event() implements graduated recovery:                 │   │
│  │                                                                      │   │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │   │
│  │  │   LOG    │───>│   SOFT   │───>│ RECLAIM  │───>│ RESTART  │      │   │
│  │  │ (Level 0)│    │ (Level 1)│    │ (Level 2)│    │ (Level 3)│      │   │
│  │  └──────────┘    └──────────┘    └──────────┘    └──────────┘      │   │
│  │       │               │               │               │            │   │
│  │       ▼               ▼               ▼               ▼            │   │
│  │  ┌──────────┐    ┌──────────┐                         ┌──────────┐ │   │
│  │  │  KEXEC   │───>│  PANIC   │                         │(escalate)│ │   │
│  │  │ (Level 4)│    │ (Level 5)│                         └──────────┘ │   │
│  │  └──────────┘    └──────────┘                                       │   │
│  │                                                                      │   │
│  │  • Per-event configurable: cooldown, max_attempts, auto-escalate    │   │
│  │  • Cooldown prevents event storms (configurable per event type)     │   │
│  │  • Auto-escalation: failed recovery at level N → try level N+1     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Recovery Executor / 恢复执行器                           │   │
│  │                                                                      │   │
│  │  • heal_kill_task(): SIGTERM → 1000ms wait → SIGKILL                │   │
│  │  • heal_reclaim_memory(): wakeup_kswapd() + wait                    │   │
│  │  • heal_reload_driver(): schedule for userspace (rmmod + insmod)    │   │
│  │  • heal_trigger_kexec(): emergency kexec (requires CONFIG_KEXEC)    │   │
│  │  • heal_recover_zombie(): SIGKILL to parent process to reap zombie  │   │
│  │  • Context-aware delays: heal_msleep() for atomic context safety    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Verification & Health Score / 验证与健康评分             │   │
│  │                                                                      │   │
│  │  Health Score (0-100):                                               │   │
│  │  • Memory pressure (weight 30)                                      │   │
│  │  • Zombie processes (weight 10)                                     │   │
│  │  • System load (weight 20)                                          │   │
│  │  • Recent events (weight 20)                                        │   │
│  │  • Recovery success rate (weight 20)                                │   │
│  │                                                                      │   │
│  │  Health Status: OK (≥80) → WARNING (≥50) → CRITICAL (<50)          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              /proc/self-heal Interface / 接口                        │   │
│  │                                                                      │   │
│  │  /proc/self-heal/                                                    │   │
│  │  ├── status    (read-only)  Current health status and statistics    │   │
│  │  ├── config    (read-write) Per-event recovery configuration        │   │
│  │  ├── trigger   (write-only) Manual event trigger                   │   │
│  │  └── history   (read-only)  Ring buffer of recent events           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Event Types / 事件类型

The system supports 13 event types, each with independent configuration:

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.h, lines 55-70 */
enum heal_event_type {
    HEAL_EVENT_MEM_PRESSURE  = 0,  /* 内存压力过高 */
    HEAL_EVENT_SOFT_LOCKUP  = 1,   /* 软锁 */
    HEAL_EVENT_HUNG_TASK    = 2,   /* 任务挂起 (D 状态) */
    HEAL_EVENT_OOM_NEAR     = 3,   /* 接近 OOM */
    HEAL_EVENT_ZOMBIE       = 4,   /* 僵尸进程过多 */
    HEAL_EVENT_MCE          = 5,   /* 机器检查错误 */
    HEAL_EVENT_PANIC        = 6,   /* 内核 panic */
    HEAL_EVENT_DRIVER       = 7,   /* 驱动错误 */
    HEAL_EVENT_FS           = 8,   /* 文件系统错误 */
    HEAL_EVENT_AI_OVERRIDE  = 9,   /* AI 决策覆盖 */
    HEAL_EVENT_OOM_KILL     = 10,  /* OOM killer 触发 */
    HEAL_EVENT_HIGH_LOAD    = 11,  /* 系统负载过高 */
    HEAL_EVENT_CUSTOM       = 12,  /* 自定义触发 */
    HEAL_EVENT_MAX,
};
```

### 5.4 Recovery Levels / 恢复级别

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.h, lines 76-84 */
enum heal_level {
    HEAL_LEVEL_LOG      = 0,  /* 仅记录，不采取行动 */
    HEAL_LEVEL_SOFT     = 1,  /* 软恢复: 杀进程/SIGTERM/SIGKILL */
    HEAL_LEVEL_RECLAIM  = 2,  /* 回收: 内存回收/cgroup 清理 */
    HEAL_LEVEL_RESTART  = 3,  /* 重启: 子系统重启/驱动重载 */
    HEAL_LEVEL_KEXEC    = 4,  /* 硬恢复: 紧急 kexec */
    HEAL_LEVEL_PANIC    = 5,  /* 紧急: 允许 panic */
    HEAL_LEVEL_NUM      = 6,
};
```

### 5.5 Default Event Configurations / 默认事件配置

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.c, lines 163-177 */
static const struct heal_event_config default_configs[HEAL_EVENT_MAX] = {
    [HEAL_EVENT_MEM_PRESSURE] = {HEAL_EVENT_MEM_PRESSURE,  HEAL_LEVEL_SOFT,    60000, 5, 1, 1, "mem_pressure"},
    [HEAL_EVENT_SOFT_LOCKUP]  = {HEAL_EVENT_SOFT_LOCKUP,   HEAL_LEVEL_RESTART, 30000, 3, 1, 1, "soft_lockup"},
    [HEAL_EVENT_HUNG_TASK]    = {HEAL_EVENT_HUNG_TASK,     HEAL_LEVEL_SOFT,    30000, 3, 1, 1, "hung_task"},
    [HEAL_EVENT_OOM_NEAR]     = {HEAL_EVENT_OOM_NEAR,      HEAL_LEVEL_SOFT,    120000,5, 1, 1, "oom_near"},
    [HEAL_EVENT_ZOMBIE]       = {HEAL_EVENT_ZOMBIE,        HEAL_LEVEL_LOG,     120000,3, 1, 1, "zombie"},
    [HEAL_EVENT_MCE]          = {HEAL_EVENT_MCE,           HEAL_LEVEL_KEXEC,   0,      1, 1, 1, "mce"},
    [HEAL_EVENT_PANIC]        = {HEAL_EVENT_PANIC,         HEAL_LEVEL_RESTART, 0,      1, 1, 1, "panic"},
    [HEAL_EVENT_DRIVER]       = {HEAL_EVENT_DRIVER,        HEAL_LEVEL_RESTART, 60000, 3, 1, 1, "driver"},
    [HEAL_EVENT_FS]           = {HEAL_EVENT_FS,            HEAL_LEVEL_RESTART, 60000, 3, 1, 1, "fs"},
    [HEAL_EVENT_AI_OVERRIDE]  = {HEAL_EVENT_AI_OVERRIDE,   HEAL_LEVEL_SOFT,    30000, 10,1, 1, "ai_override"},
    [HEAL_EVENT_OOM_KILL]     = {HEAL_EVENT_OOM_KILL,      HEAL_LEVEL_LOG,     60000, 3, 1, 1, "oom_kill"},
    [HEAL_EVENT_HIGH_LOAD]    = {HEAL_EVENT_HIGH_LOAD,     HEAL_LEVEL_SOFT,    60000, 3, 1, 1, "high_load"},
    [HEAL_EVENT_CUSTOM]       = {HEAL_EVENT_CUSTOM,        HEAL_LEVEL_SOFT,    30000, 5, 1, 1, "custom"},
};
```

### 5.6 Graduated Recovery Algorithm / 渐变恢复算法

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.c, lines 1021-1145 */
static int heal_process_event(enum heal_event_type type,
                              enum heal_level level_override,
                              pid_t pid,
                              const char *description)
{
    // 1. Check initialization and cooldown
    // 2. Get configuration for the event type
    // 3. Set recovery_in_progress flag (prevent recursion)
    // 4. Graduated recovery loop:
    while (current_level <= max_level && attempts < max_recovery_attempts) {
        attempts++;
        ret = heal_execute_recovery(type, current_level);
        if (ret == 0) {
            // Success: record and break
            break;
        }
        // Failure: escalate to next level
        if (current_level < max_level) {
            current_level++;
            escalated = true;
            heal_msleep(100);  // Brief delay before escalation
        }
    }
    // 5. Record event in ring buffer
    // 6. Update health score and status
    // 7. Return result
}
```

### 5.7 Health Score Calculation / 健康评分计算

The health score (0-100) is calculated from multiple weighted factors:

| Factor | Weight | Components |
|--------|--------|------------|
| Memory Pressure | 30 | Free memory percentage vs thresholds (5% critical, 10% warning) |
| Zombie Processes | 10 | Zombie count vs thresholds (50 critical, 20 warning) |
| System Load | 20 | Load average vs CPU count multipliers (8x critical, 4x warning) |
| Recent Events | 20 | Events detected count (100+ = -20, 50+ = -10, 10+ = -5) |
| Recovery Success Rate | 20 | Success percentage (below 30% = -20, below 60% = -10) |

### 5.8 IOCTL Commands / IOCTL 命令

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.h, lines 38-49 */
#define SELF_HEAL_IOC_MAGIC  'H'

#define SELF_HEAL_TRIGGER    _IOW(SELF_HEAL_IOC_MAGIC, 1, struct heal_trigger_cmd)
#define SELF_HEAL_GET_CONFIG _IOR(SELF_HEAL_IOC_MAGIC, 2, struct heal_event_config)
#define SELF_HEAL_SET_CONFIG _IOW(SELF_HEAL_IOC_MAGIC, 3, struct heal_event_config)
#define SELF_HEAL_GET_STATS  _IOR(SELF_HEAL_IOC_MAGIC, 4, struct heal_stats)
#define SELF_HEAL_RESET      _IO(SELF_HEAL_IOC_MAGIC, 5)
```

### 5.9 Key Data Structures / 关键数据结构

```c
/* From D:/Ainos/kernel/ai-self-heal/self_heal.h, lines 93-150 */

/* 事件配置 (每个事件类型可独立配置) */
struct heal_event_config {
    __u32  type;             /* enum heal_event_type */
    __u32  level;            /* enum heal_level - 恢复级别 */
    __u32  cooldown_ms;      /* 冷却时间 (ms) */
    __u32  max_attempts;     /* 最大尝试次数 (0 = 无限) */
    __u32  enabled;          /* 1=启用, 0=禁用 */
    __u32  auto_escalate;    /* 1=自动升级, 0=失败即停止 */
    char   name[32];         /* 可读名称 */
};

/* 触发命令 */
struct heal_trigger_cmd {
    __u32  type;             /* enum heal_event_type */
    __u32  level;            /* enum heal_level - 覆盖恢复级别 */
    pid_t  pid;              /* 目标 PID (可选) */
    char   reason[128];      /* 触发原因 */
};

/* 事件记录 (环形缓冲区条目) */
struct heal_event_record {
    __u64  timestamp_ns;
    __u32  type;
    __u32  level_used;
    __u32  level_escalated;
    __s32  result;
    __u32  pid;
    __u32  seq;
    char   comm[16];
    char   description[128];
};

/* 统计 */
struct heal_stats {
    __u64  events_detected;
    __u64  recovery_attempts;
    __u64  recovery_success;
    __u64  recovery_failed;
    __u64  escalation_count;
    __u64  prevention_actions;
    __u64  oom_kills;
    __u64  tasks_killed;
    __u64  drivers_reloaded;
    __u64  kexec_triggers;
    __u64  last_event_ns;
    __u32  current_level;
    __u32  health_score;
    __u64  uptime_ms;
};

/* 健康状态枚举 */
enum heal_health_status {
    HEAL_HEALTH_OK        = 0,
    HEAL_HEALTH_WARNING   = 1,
    HEAL_HEALTH_CRITICAL  = 2,
    HEAL_HEALTH_RECOVERING= 3,
    HEAL_HEALTH_UNKNOWN   = 4,
};
```

### 5.10 Exported Functions / 导出函数

| Function | Purpose |
|----------|---------|
| `self_heal_report_event()` | Report an event (uses default level from config) |
| `self_heal_report_event_level()` | Report an event with explicit level override |
| `self_heal_get_health()` | Get current health status |
| `self_heal_get_health_score()` | Get current health score (0-100) |
| `self_heal_force_recovery()` | Force immediate recovery action |

### 5.11 Safety Design / 安全设计

The self-healing module includes several safety mechanisms:

1. **Context awareness**: Distinguishes between panic atomic context and workqueue sleepable context
2. **Lock ordering**: `spinlock(ring) -> mutex(config) -> mutex(monitor)`
3. **No self-deadlock**: Recovery does not trigger monitoring while executing; monitoring does not trigger recovery
4. **Cooldown periods**: Same-type events within cooldown interval are silently skipped
5. **Rollback on failure**: If recovery fails, automatic escalation to higher level
6. **Atomic context safety**: `heal_msleep()` uses `mdelay()` in atomic context, skips in NMI/panic

---

## 6. Hotpatch System / 热补丁系统

### 6.1 Overview / 概述

The Hotpatch system provides runtime kernel function patching capabilities for AinosOS. It allows registered patches to be applied to running kernel functions using x86_64 JMP rel32 instruction modification, with safety checks, rollback capability, and kprobe-based monitoring hooks.

热补丁系统为 AinosOS 提供运行时内核函数修补能力。它允许将注册的补丁应用于正在运行的内核函数，使用 x86_64 JMP rel32 指令修改，具有安全检查、回滚能力和基于 kprobe 的监控钩子。

**Source files:** `D:/Ainos/kernel/hotpatch/hotpatch.c`, `D:/Ainos/kernel/hotpatch/hotpatch.h`

### 6.2 Architecture / 架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      Hotpatch Engine / 热补丁引擎                             │
│                      Version 2.0.0                                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Patch Manager / 补丁管理器                          │   │
│  │                                                                      │   │
│  │  hotpatch_register() → hotpatch_apply() → hotpatch_rollback()        │   │
│  │                                                                      │   │
│  │  Patch States:                                                       │   │
│  │  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │   │
│  │  │  REGISTERED  │───>│   APPLIED    │───>│  ROLLEDBACK  │           │   │
│  │  │      (0)     │    │     (1)      │    │     (2)      │           │   │
│  │  └──────────────┘    └──────────────┘    └──────────────┘           │   │
│  │         │                                                           │   │
│  │         ▼                                                           │   │
│  │  ┌──────────────┐                                                   │   │
│  │  │    FAILED    │                                                   │   │
│  │  │     (3)      │                                                   │   │
│  │  └──────────────┘                                                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Safety Check / 安全检查                                  │   │
│  │                                                                      │   │
│  │  check_patch_safety():                                               │   │
│  │  1. target_addr and patch_addr are valid                             │   │
│  │  2. target != patch (can't patch with itself)                        │   │
│  │  3. Not self-patching (patch not in hotpatch module)                │   │
│  │  4. target_addr is in kernel text segment (_stext to _etext)         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Patching Executor (stop_machine) / 修补执行器            │   │
│  │                                                                      │   │
│  │  do_patch_cb() runs in stop_machine context (all CPUs stopped):      │   │
│  │                                                                      │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  Apply:                                                      │   │   │
│  │  │  1. Build JMP rel32: E9 <4-byte signed offset>              │   │   │
│  │  │     offset = patch_addr - (target_addr + 5)                 │   │   │
│  │  │  2. Backup original 5 bytes at target                       │   │   │
│  │  │  3. Write JMP instruction to target                         │   │   │
│  │  │  4. Flush TLB and sync_core()                               │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────────────┐   │   │
│  │  │  Rollback:                                                   │   │   │
│  │  │  1. Verify current bytes match expected JMP or original      │   │   │
│  │  │  2. Restore original 5 bytes                                 │   │   │
│  │  │  3. Flush TLB and sync_core()                                │   │   │
│  │  └──────────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Monitoring Hooks (kprobe) / 监控钩子                    │   │
│  │                                                                      │   │
│  │  hotpatch_register_hook() → register_kprobe()                       │   │
│  │                                                                      │   │
│  │  Each hook tracks:                                                   │   │
│  │  • call_count: Number of times the function was called               │   │
│  │  • error_count: Number of times detect_fn returned non-zero         │   │
│  │  • detect_fn: Custom detection function called on each invocation    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              Auto-Generation / 自动生成                               │   │
│  │                                                                      │   │
│  │  hotpatch_autogen() framework:                                      │   │
│  │  1. Extract function prototype from fault_func                      │   │
│  │  2. Analyze error context                                           │   │
│  │  3. Generate fix code (null checks, bounds checks, etc.)            │   │
│  │  4. Compile as kernel module                                        │   │
│  │  5. Dynamic load (requires userspace toolchain)                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│                                    ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │              /proc/ai-hotpatch Interface / 接口                      │   │
│  │                                                                      │   │
│  │  /proc/ai-hotpatch/                                                  │   │
│  │  ├── status    (read-only)  Hotpatch engine status & statistics     │   │
│  │  ├── patches   (read-only)  List of all registered patches          │   │
│  │  ├── hooks     (read-only)  List of monitoring hooks with counters  │   │
│  │  └── config    (read-only)  Module configuration parameters         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Patch States / 补丁状态

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.h, lines 10-15 */
enum hotpatch_status {
    HOTPATCH_REGISTERED = 0,  /* 已注册，尚未应用 */
    HOTPATCH_APPLIED    = 1,  /* 已应用，正在生效 */
    HOTPATCH_ROLLEDBACK = 2,  /* 已回滚 */
    HOTPATCH_FAILED     = 3,  /* 失败 */
};
```

### 6.4 Patching Mechanism / 修补机制 (x86_64)

The patching mechanism uses x86_64 `JMP rel32` instruction (opcode `0xE9` followed by a 4-byte signed offset):

```
JMP rel32 instruction format:
  Byte 0:    0xE9 (JMP rel32 opcode)
  Bytes 1-4: <4-byte signed offset>

Offset calculation:
  offset = patch_addr - (target_addr + 5)
  (The +5 accounts for the JMP rel32 instruction length)

Example:
  target_addr = 0xffffffff81234560
  patch_addr  = 0xffffffff81345670
  offset = 0xffffffff81345670 - (0xffffffff81234560 + 5)
         = 0x11110B
  JMP bytes: E9 0B 11 11 00
```

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.c, lines 232-298 */
static int do_patch_cb(void *data)
{
    struct patch_work *pw = data;
    u8 jmp_code[JMP_INSN_SIZE];
    s32 offset;

    if (pw->apply) {
        /* 构建 JMP rel32 指令 */
        jmp_code[0] = 0xE9;  /* JMP rel32 opcode */
        offset = (s32)((unsigned long)pw->patch_addr -
                       ((unsigned long)pw->target_addr + 5));

        /* 安全检查: offset 必须能放入 32 位有符号整数 */
        s64 offset_64 = (s64)((unsigned long)pw->patch_addr -
                              ((unsigned long)pw->target_addr + 5));
        if (offset_64 > (s64)0x7FFFFFFF || offset_64 < (s64)(-0x7FFFFFFF - 1)) {
            pw->result = -ERANGE;
            return 0;
        }

        memcpy(&jmp_code[1], &offset, 4);
        memcpy(pw->orig_bytes, pw->target_addr, JMP_INSN_SIZE);
        memcpy(pw->target_addr, jmp_code, JMP_INSN_SIZE);
    } else {
        /* Rollback: verify and restore */
        u8 current_bytes[JMP_INSN_SIZE];
        memcpy(current_bytes, pw->target_addr, JMP_INSN_SIZE);
        // ... verify then restore ...
        memcpy(pw->target_addr, pw->orig_bytes, JMP_INSN_SIZE);
    }

    __flush_tlb_all();
    sync_core();
    pw->result = 0;
    return 0;
}
```

### 6.5 Safety Checks / 安全检查

Before applying a patch, the system performs comprehensive safety verification:

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.c, lines 181-218 */
static int check_patch_safety(struct hotpatch_entry *entry)
{
    // 1. Both addresses must be valid
    if (!entry->target_addr || !entry->patch_addr)
        return -EINVAL;

    // 2. Cannot patch with itself
    if (entry->target_addr == entry->patch_addr)
        return -EINVAL;

    // 3. No self-patching (patch in hotpatch module)
    struct module *self = THIS_MODULE;
    unsigned long patch_addr_val = (unsigned long)entry->patch_addr;
    if (patch_addr_val >= (unsigned long)self->module_core &&
        patch_addr_val < (unsigned long)self->module_core + self->core_size)
        return -EPERM;

    // 4. Target must be in kernel text segment
    unsigned long addr = (unsigned long)entry->target_addr;
    if (addr < (unsigned long)_stext || addr >= (unsigned long)_etext)
        return -EPERM;

    entry->safety_ok = 1;
    return 0;
}
```

### 6.6 Monitoring Hooks / 监控钩子

Monitoring hooks use kprobes to intercept function calls:

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.c, lines 554-611 */
static int hook_handler_pre(struct kprobe *p, struct pt_regs *regs)
{
    struct hook_entry *entry = container_of(p, struct hook_entry, kp);
    entry->call_count++;
    g_hp.stats.total_hook_calls++;

    if (entry->detect_fn) {
        if (entry->detect_fn(regs)) {
            entry->error_count++;
            g_hp.stats.total_hook_errors++;
        }
    }
    return 0;
}

int hotpatch_register_hook(const char *func_name,
                           int (*detect)(struct pt_regs *))
{
    // ... allocate and register kprobe ...
    entry->kp.symbol_name = func_name;
    entry->kp.pre_handler = hook_handler_pre;
    ret = register_kprobe(&entry->kp);
    // ...
}
```

### 6.7 Auto-Generation from Fault Context / 基于故障上下文的自动生成

The `hotpatch_autogen()` function provides a framework for automatic patch generation from fault context. The current implementation is a placeholder that logs the intent:

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.c, lines 644-666 */
int hotpatch_autogen(const char *fault_func, const char *context)
{
    pr_info("hotpatch: auto-generate patch for '%s'\n", fault_func);
    pr_info("hotpatch: context: %s\n", context ?: "none");

    /*
     * 自动生成补丁的完整实现需要:
     * 1. 从 fault_func 提取函数原型
     * 2. 分析 context 中的错误信息
     * 3. 生成修复代码 (如: 空指针检查、边界检查)
     * 4. 编译为内核模块
     * 5. 动态加载
     */
    return 0;
}
```

### 6.8 Integration with Self-Healing / 与自愈系统集成

The hotpatch system integrates with the self-healing subsystem through the `HEAL_EVENT_AI_OVERRIDE` event type. When the self-healing system detects an anomaly that requires a code-level fix, it can trigger hotpatch to generate and apply a runtime patch.

The integration flow:
1. Self-healing detects an anomaly (e.g., `HEAL_EVENT_DRIVER`)
2. If configured, the AI_OVERRIDE event is triggered
3. The hotpatch autogen framework is invoked to create a patch
4. The patch is applied via `stop_machine`
5. Self-healing verifies the fix worked

### 6.9 Statistics / 统计

```c
/* From D:/Ainos/kernel/hotpatch/hotpatch.h, lines 37-46 */
struct hotpatch_stats {
    __u32  patches_total;        /* 补丁总数 */
    __u32  patches_applied;      /* 已应用 */
    __u32  patches_rolledback;   /* 已回滚 */
    __u32  patches_failed;       /* 失败 */
    __u32  hooks_total;          /* 钩子总数 */
    __u64  total_hook_calls;     /* 钩子调用次数 */
    __u64  total_hook_errors;    /* 钩子错误次数 */
    __u32  safety_failures;      /* 安全检查失败次数 */
};
```

### 6.10 Exported Functions / 导出函数

| Function | Purpose |
|----------|---------|
| `hotpatch_register()` | Register a new patch for a target function |
| `hotpatch_apply()` | Apply a registered patch |
| `hotpatch_rollback()` | Rollback an applied patch |
| `hotpatch_register_hook()` | Register a kprobe monitoring hook |
| `hotpatch_unregister_hook()` | Unregister a monitoring hook |
| `hotpatch_get_info()` | Get patch information |
| `hotpatch_get_stats()` | Get hotpatch statistics |
| `hotpatch_autogen()` | Auto-generate patch from fault context |

---

## 7. ABI Specification / ABI 规范

### 7.1 Overview / 概述

This section defines the AinosOS AI subsystem ABI -- the interface between kernel space and userspace, including system call numbers, data structures, IOCTL commands, and error codes.

本节定义 AinosOS AI 子系统 ABI -- 内核空间与用户空间之间的接口，包括系统调用号、数据结构、IOCTL 命令和错误码。

**Source file:** `D:/Ainos/kernel/include/ainos/ai-abi.h`

### 7.2 System Call Numbers / 系统调用号

AinosOS reserves Linux syscall numbers 450-459 for its AI subsystem:

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 26-33 */
#define __NR_ai_inference       450   /* AI 推理请求 */
#define __NR_ai_embedding       451   /* 文本嵌入 */
#define __NR_ai_semantic_search 452   /* 语义搜索 */
#define __NR_ai_model_load      453   /* 加载模型 */
#define __NR_ai_model_unload    454   /* 卸载模型 */
#define __NR_ai_context_store   455   /* 存储上下文 */
#define __NR_ai_context_retrieve 456  /* 检索上下文 */
#define __NR_ai_status          457   /* 获取系统状态 */
```

### 7.3 Data Structures / 数据结构

#### 7.3.1 AI Inference Request / AI 推理请求

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 60-76 */
struct ai_inference_req {
    uint64_t model_id;                 /* 模型 ID */
    uint64_t session_id;               /* 会话 ID (0 = 新会话) */
    enum ai_task_priority priority;    /* 优先级 */

    /* 输入数据 */
    const char __user *prompt;         /* 输入文本 */
    uint64_t prompt_len;               /* 输入长度 */
    const float __user *images;        /* 图像数据 (可选) */
    uint64_t image_count;              /* 图像数量 */

    /* 推理参数 */
    float temperature;                 /* 温度 (0.0 - 2.0) */
    float top_p;                       /* Top-P 采样 */
    uint32_t max_tokens;               /* 最大输出 token 数 */
    uint32_t context_len;              /* 上下文窗口大小 */
};
```

#### 7.3.2 AI Inference Response / AI 推理响应

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 81-94 */
struct ai_inference_resp {
    uint64_t task_id;                  /* 任务 ID (用于异步查询) */
    enum ai_task_status status;        /* 任务状态 */

    /* 输出数据 */
    char __user *output;               /* 输出文本缓冲区 */
    uint64_t output_len;               /* 实际输出长度 */
    uint64_t output_capacity;          /* 缓冲区容量 */

    /* 统计信息 */
    uint64_t tokens_generated;         /* 生成 token 数 */
    uint64_t inference_ms;             /* 推理耗时 (毫秒) */
    uint64_t total_ms;                 /* 总耗时 (含排队) */
};
```

#### 7.3.3 Semantic Search Result / 语义搜索结果

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 99-108 */
#define AI_SEARCH_PATH_LEN 512
#define AI_SEARCH_SNIPPET_LEN 256

struct ai_search_result {
    char path[AI_SEARCH_PATH_LEN];       /* 文件路径 */
    char snippet[AI_SEARCH_SNIPPET_LEN]; /* 匹配片段 */
    float score;                          /* 相关度分数 (0-1) */
    uint64_t file_size;                   /* 文件大小 */
    uint64_t modified_at;                 /* 修改时间戳 */
};
```

#### 7.3.4 AI System Status / AI 系统状态

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 113-123 */
struct ai_system_status {
    uint32_t models_loaded;           /* 已加载模型数 */
    uint32_t tasks_pending;           /* 排队任务数 */
    uint32_t tasks_running;           /* 运行中任务数 */
    uint64_t total_inferences;        /* 总推理次数 */
    uint64_t total_tokens;            /* 总生成 token 数 */
    uint64_t uptime_ms;               /* 运行时间 */
    uint8_t  network_available;       /* 网络是否可用 */
    uint8_t  accelerator_type;        /* 加速器类型: 0=CPU, 1=GPU, 2=NPU, 3=VPU */
    char     version[64];             /* AI 子系统版本 */
};
```

#### 7.3.5 Context Entry / 上下文条目

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 128-137 */
#define AI_CONTEXT_KEY_MAX 128
#define AI_CONTEXT_VAL_MAX 65536

struct ai_context_entry {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    char __user *value;
    uint64_t value_len;
    uint64_t value_capacity;
};
```

#### 7.3.6 Embedding Request / 嵌入请求

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 150-155 */
struct ai_embedding_req {
    const float __user *input;
    uint64_t input_len;
    float __user *embedding;
    uint64_t embedding_dim;
};
```

Valid embedding dimensions: 128, 256, 512, 768, 1024, 2048, 4096.

```c
/* From D:/Ainos/kernel/ai-syscalls-main.c, lines 62-75 */
static const size_t ai_valid_dims[] = {
    128, 256, 512, 768, 1024, 2048, 4096
};

static bool is_valid_embedding_dim(size_t dim)
{
    size_t i;
    for (i = 0; i < ARRAY_SIZE(ai_valid_dims); i++) {
        if (ai_valid_dims[i] == dim)
            return true;
    }
    return false;
}
```

#### 7.3.7 Search Request / 搜索请求

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 160-168 */
struct ai_search_req {
    const float __user *query_emb;
    uint64_t query_dim;
    const float __user *database;
    uint64_t db_size;
    uint64_t vector_dim;
    uint32_t top_k;
    struct ai_search_result __user *results;
};
```

#### 7.3.8 Model Load Request / 模型加载请求

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 176-179 */
#define AI_MODEL_NAME_MAX 64
#define AI_MODEL_PATH_MAX 512

struct ai_model_load_req {
    char name[AI_MODEL_NAME_MAX];
    char path[AI_MODEL_PATH_MAX];
};
```

#### 7.3.9 Context Store / 上下文存储

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 184-190 */
struct ai_context_store_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    const char __user *value;
    uint64_t value_len;
    uint64_t ttl_ms;        /* 生存时间 (毫秒) */
};
```

#### 7.3.10 Context Retrieve / 上下文检索

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 192-199 */
struct ai_context_retrieve_req {
    uint64_t session_id;
    char key[AI_CONTEXT_KEY_MAX];
    uint64_t entry_id;
    char __user *value;
    uint64_t value_capacity;
    uint64_t __user *value_len;
};
```

### 7.4 IOCTL Commands / IOCTL 命令

The IOCTL magic number is `'A'` (ASCII 0x41):

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 204-211 */
#define AI_IOC_MAGIC  'A'

#define AI_IOCTL_GET_STATUS    _IOR(AI_IOC_MAGIC, 1, struct ai_system_status)
#define AI_IOCTL_LOAD_MODEL    _IOW(AI_IOC_MAGIC, 2, uint64_t)
#define AI_IOCTL_UNLOAD_MODEL  _IOW(AI_IOC_MAGIC, 3, uint64_t)
#define AI_IOCTL_CANCEL_TASK   _IOW(AI_IOC_MAGIC, 4, uint64_t)
#define AI_IOCTL_GET_TASK_STAT _IOR(AI_IOC_MAGIC, 5, uint64_t)
#define AI_IOCTL_SET_VERBOSE   _IOW(AI_IOC_MAGIC, 6, uint8_t)
```

#### 7.4.1 Power Policy IOCTLs / 电源策略 IOCTL

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 255-257 */
#define AI_IOCTL_GET_POWER_MODE _IOR(AI_IOC_MAGIC, 7, struct ai_power_status)
#define AI_IOCTL_SET_POWER_MODE _IOW(AI_IOC_MAGIC, 8, enum ai_power_mode)
#define AI_IOCTL_GET_TEMP       _IOR(AI_IOC_MAGIC, 9, uint32_t)
```

### 7.5 Error Codes / 错误码

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 216-226 */
#define AI_ERR_SUCCESS          0    /* 成功 */
#define AI_ERR_GENERAL          -1   /* 通用错误 */
#define AI_ERR_INVALID_PARAM    -2   /* 无效参数 */
#define AI_ERR_MODEL_NOT_FOUND  -3   /* 模型未找到 */
#define AI_ERR_MODEL_LOAD_FAIL  -4   /* 模型加载失败 */
#define AI_ERR_OUT_OF_MEMORY    -5   /* 内存不足 */
#define AI_ERR_TASK_QUEUE_FULL  -6   /* 任务队列已满 */
#define AI_ERR_NOT_SUPPORTED    -7   /* 不支持的操作 */
#define AI_ERR_PERMISSION       -8   /* 权限不足 */
#define AI_ERR_TIMEOUT          -9   /* 操作超时 */
#define AI_ERR_THERMAL_THROTTLE -10  /* 热节流，无法执行 */
```

### 7.6 Power Policy / 电源策略

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 237-252 */
enum ai_power_mode {
    AI_POWER_MAX       = 0,  /* < 70°C: 全速模式 (AVX-256, 4核推理, FP32) */
    AI_POWER_BALANCED  = 1,  /* 70-85°C: 平衡模式 (AVX-128, 2核推理, FP16) */
    AI_POWER_EFFICIENT = 2,  /* > 85°C: 节能模式 (NEON/标量, 1核推理, INT8) */
    AI_POWER_EMERGENCY = 3,  /* > 95°C: 紧急模式 (仅标量, 1核推理, INT4) */
};

struct ai_power_status {
    enum ai_power_mode  current_mode;         /* 当前策略模式 */
    uint32_t            cpu_temp;             /* 当前 CPU 温度 (毫摄氏度) */
    uint32_t            cpu_temp_decicelsius; /* 十分之一摄氏度 */
    uint32_t            recommended_threads;  /* 推荐推理线程数 */
    uint8_t             throttle_active;      /* 是否正在降频 */
    uint8_t             sensor_available;     /* 温度传感器是否可用 */
};
```

### 7.7 Task Priority / 任务优先级

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 38-44 */
enum ai_task_priority {
    AI_PRIO_BACKGROUND = 0,   /* 后台任务，不抢占用户交互 */
    AI_PRIO_LOW,              /* 低优先级 */
    AI_PRIO_NORMAL,           /* 普通优先级 */
    AI_PRIO_HIGH,             /* 高优先级 */
    AI_PRIO_REALTIME,         /* 实时，仅限系统服务 */
};
```

### 7.8 Task Status / 任务状态

```c
/* From D:/Ainos/kernel/include/ainos/ai-abi.h, lines 49-55 */
enum ai_task_status {
    AI_TASK_PENDING    = 0,   /* 排队中 */
    AI_TASK_RUNNING    = 1,   /* 执行中 */
    AI_TASK_COMPLETED  = 2,   /* 完成 */
    AI_TASK_FAILED     = 3,   /* 失败 */
    AI_TASK_CANCELLED  = 4,   /* 已取消 */
};
```

---

## Appendix A: Source File Index / 源文件索引

| Subsystem | File | Path |
|-----------|------|------|
| AI Scheduler | Main module | `D:/Ainos/kernel/ai-scheduler-main.c` |
| AI Scheduler | Syscalls implementation | `D:/Ainos/kernel/ai-syscalls-main.c` |
| Vector Acceleration | Main module | `D:/Ainos/kernel/ai-vector-accel-main.c` |
| Vector Acceleration | x86 AVX2 | `D:/Ainos/kernel/arch/x86/avx2_impl.c` |
| Vector Acceleration | x86 AVX-512 | `D:/Ainos/kernel/arch/x86/avx512_impl.c` |
| Vector Acceleration | x86 AMX | `D:/Ainos/kernel/arch/x86/amx_impl.c` |
| Vector Acceleration | x86 SIMD header | `D:/Ainos/kernel/arch/x86/simd_impl.h` |
| Vector Acceleration | x86 Benchmark | `D:/Ainos/kernel/arch/x86/simd_benchmark.c` |
| Vector Acceleration | ARM64 NEON | `D:/Ainos/kernel/arch/arm64/neon_impl.c` |
| Vector Acceleration | ARM64 SVE | `D:/Ainos/kernel/arch/arm64/sve_impl.c` |
| Vector Acceleration | ARM64 SIMD header | `D:/Ainos/kernel/arch/arm64/simd_impl.h` |
| Vector Acceleration | Sysfs interface | `D:/Ainos/kernel/arch/ai-vector-sysfs.c` |
| Memory Management | AI tmpfs | `D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.c` |
| Memory Management | AI tmpfs header | `D:/Ainos/kernel/ai-tmpfs/ai_tmpfs.h` |
| Process Management | AI KILL | `D:/Ainos/kernel/ai-kill/ai_kill.c` |
| Process Management | AI KILL header | `D:/Ainos/kernel/ai-kill/ai_kill.h` |
| Process Management | AI-proc VFS | `D:/Ainos/kernel/ai-proc/proc_ai.c` |
| Process Management | AI-proc header | `D:/Ainos/kernel/ai-proc/proc_ai.h` |
| Process Management | AI-proc bridge | `D:/Ainos/kernel/ai-proc/ai-proc-bridge.c` |
| Self-Healing | Main module | `D:/Ainos/kernel/ai-self-heal/self_heal.c` |
| Self-Healing | Header | `D:/Ainos/kernel/ai-self-heal/self_heal.h` |
| Hotpatch | Main module | `D:/Ainos/kernel/hotpatch/hotpatch.c` |
| Hotpatch | Header | `D:/Ainos/kernel/hotpatch/hotpatch.h` |
| ABI | ABI definitions | `D:/Ainos/kernel/include/ainos/ai-abi.h` |
| Build | Makefile | `D:/Ainos/kernel/Makefile` |
| Build | AI readahead | `D:/Ainos/kernel/ai-readahead/ai_readahead.c` |

## Appendix B: Architecture Summary / 架构总结

```
AinosOS Kernel Subsystems
=========================

┌──────────────────────────────────────────────────────────────────────────────┐
│                              Userspace                                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐    │
│  │  User    │  │  ai-proc │  │  ai-     │  │  /proc/self-heal         │    │
│  │  App     │  │  -bridge │  │  daemon  │  │  /proc/ai-kill           │    │
│  │          │  │(TCP/9500)│  │          │  │  /proc/ai-hotpatch       │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────┬───────────────┘    │
│       │             │             │                    │                     │
├───────┼─────────────┼─────────────┼────────────────────┼──────────────────────┤
│       │    Syscall  │   IOCTL     │    /proc fs        │    /sys/class        │
│       ▼             ▼             ▼                    ▼                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        System Call Layer (450-457)                   │   │
│  │  D:/Ainos/kernel/ai-syscalls-main.c                                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│        ┌───────────────────────────┼───────────────────────────────┐         │
│        ▼                           ▼                               ▼         │
│  ┌──────────┐               ┌──────────────┐               ┌──────────────┐ │
│  │ AI       │               │ Self-Healing │               │  Hotpatch    │ │
│  │ Scheduler│               │ (self_heal)  │               │ (hotpatch)   │ │
│  │          │               │ • 13 events  │               │ • JMP rel32  │ │
│  │ • 5-queue│               │ • 6 levels   │               │ • kprobe     │ │
│  │ • 4 work │               │ • Health     │               │ • Safety ck │ │
│  │ • Thermal│               │   score      │               │ • Rollback   │ │
│  │ • Watch- │               │ • Ring buf   │               │ • Auto-gen   │ │
│  │   dog    │               │ • Notifier   │               │              │ │
│  └────┬─────┘               └──────┬───────┘               └──────┬───────┘ │
│       │                            │                              │         │
│       ▼                            ▼                              ▼         │
│  ┌──────────┐               ┌──────────────┐               ┌──────────────┐ │
│  │ Vector   │               │  AI KILL     │               │  AI tmpfs    │ │
│  │ Accel    │               │  (ai_kill)   │               │  (ai_tmpfs)  │ │
│  │          │               │ • 7-dim scr  │               │ • Hot/Warm/  │ │
│  │ • AVX2   │               │ • Whitelist  │               │   Cold       │ │
│  │ • AVX512 │               │ • Rate limit │               │ • LRU list   │ │
│  │ • AMX    │               │ • Behavior   │               │ • Shrinker   │ │
│  │ • NEON   │               │   tracking   │               │ • Model cache│ │
│  │ • SVE    │               │              │               │ • KV-cache   │ │
│  └──────────┘               └──────────────┘               └──────────────┘ │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        ABI Definition                                  │   │
│  │  D:/Ainos/kernel/include/ainos/ai-abi.h                               │   │
│  │  Syscalls: 450-457 | IOCTL Magic: 'A' | Error codes: AI_ERR_*        │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

*Document generated from AinosOS kernel source tree at `D:/Ainos/kernel/`.*
*此文档由 AinosOS 内核源码树 `D:/Ainos/kernel/` 生成。*