// Ainos OS - Platform Abstraction Layer (PAL)
// 跨平台抽象层: 为 AinosOS 提供统一的 Windows/Linux/macOS 接口
//
// Copyright (c) 2024 AinosOS
// SPDX-License-Identifier: MIT
//
// 使用方式:
//   #include <ainos/platform.h>
//   编译时链接对应平台的实现文件即可
//
//   Linux:   ainos_platform_linux.c   (-lpthread -ldl -lrt)
//   Windows: ainos_platform_win32.c   (-lws2_32)
//   macOS:   ainos_platform_darwin.c  (-lpthread -ldl -framework IOKit)

#ifndef AINOS_PLATFORM_H
#define AINOS_PLATFORM_H

#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ================================================================
 * 1. 平台检测宏
 * ================================================================
 * 根据编译器预定义宏自动检测目标平台。
 * 应用代码应使用 AINOS_PLATFORM_WIN32 / AINOS_PLATFORM_LINUX /
 * AINOS_PLATFORM_DARWIN / AINOS_PLATFORM_UNIX 进行条件编译。
 */

#if defined(_WIN32) || defined(_WIN64)
#  define AINOS_PLATFORM_WIN32 1
#  define AINOS_PLATFORM_UNIX  0
#  define AINOS_PLATFORM_LINUX 0
#  define AINOS_PLATFORM_DARWIN 0
#elif defined(__APPLE__) && defined(__MACH__)
#  include <TargetConditionals.h>
#  if TARGET_OS_OSX || TARGET_OS_MAC
#    define AINOS_PLATFORM_DARWIN 1
#    define AINOS_PLATFORM_MACOS 1
#  else
#    error "Unsupported Apple platform"
#  endif
#  define AINOS_PLATFORM_UNIX  1
#  define AINOS_PLATFORM_LINUX 0
#  define AINOS_PLATFORM_WIN32 0
#elif defined(__linux__) || defined(__linux)
#  define AINOS_PLATFORM_LINUX  1
#  define AINOS_PLATFORM_UNIX   1
#  define AINOS_PLATFORM_WIN32  0
#  define AINOS_PLATFORM_DARWIN 0
#else
#  error "AinosOS: Unsupported platform. AinosOS requires Windows, Linux, or macOS."
#endif

/* ================================================================
 * 2. 版本信息
 * ================================================================ */

#define AINOS_PLATFORM_VERSION_MAJOR 1
#define AINOS_PLATFORM_VERSION_MINOR 0
#define AINOS_PLATFORM_VERSION_PATCH 0
#define AINOS_PLATFORM_VERSION       "1.0.0"

/* ================================================================
 * 3. 通用错误码
 * ================================================================
 * 所有平台抽象函数返回 int，0 表示成功，负值表示错误。
 */

#define AINOS_PLATFORM_OK              0
#define AINOS_PLATFORM_ERR_GENERAL    -1
#define AINOS_PLATFORM_ERR_NOMEM      -2
#define AINOS_PLATFORM_ERR_INVAL      -3
#define AINOS_PLATFORM_ERR_TIMEOUT    -4
#define AINOS_PLATFORM_ERR_BUSY       -5
#define AINOS_PLATFORM_ERR_AGAIN      -6
#define AINOS_PLATFORM_ERR_NOT_FOUND  -7
#define AINOS_PLATFORM_ERR_PERM       -8
#define AINOS_PLATFORM_ERR_EXIST      -9
#define AINOS_PLATFORM_ERR_IO         -10
#define AINOS_PLATFORM_ERR_INTR       -11
#define AINOS_PLATFORM_ERR_NOT_SUP    -12
#define AINOS_PLATFORM_ERR_CONNREFUSED -13
#define AINOS_PLATFORM_ERR_CONNRESET  -14
#define AINOS_PLATFORM_ERR_ADDRINUSE  -15
#define AINOS_PLATFORM_ERR_WOULDBLOCK -16

/* ================================================================
 * 4. 抽象类型定义
 * ================================================================
 * 这些类型在平台实现文件中定义为具体结构体，在头文件中保持 opaque。
 * 应用代码通过指针使用，不关心内部布局。
 */

/* ---------- 4.1 互斥锁 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_mutex {
    void* _critical_section;  /* CRITICAL_SECTION */
    int    _is_initialized;
    int    _is_recursive;
    void* _native_handle;     /* SRWLOCK fallback */
} ainos_platform_mutex_t;
#else
typedef struct ainos_platform_mutex {
    void* _pthread_mutex;     /* pthread_mutex_t */
    int   _is_initialized;
    int   _is_recursive;
    int   _type;              /* NORMAL / RECURSIVE / ERRORCHECK */
} ainos_platform_mutex_t;
#endif

/* ---------- 4.2 读写锁 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_rwlock {
    void* _srwlock;           /* SRWLOCK */
    int   _is_initialized;
} ainos_platform_rwlock_t;
#else
typedef struct ainos_platform_rwlock {
    void* _pthread_rwlock;    /* pthread_rwlock_t */
    int   _is_initialized;
} ainos_platform_rwlock_t;
#endif

/* ---------- 4.3 条件变量 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_cond {
    void* _cond_var;          /* CONDITION_VARIABLE */
    int   _is_initialized;
} ainos_platform_cond_t;
#else
typedef struct ainos_platform_cond {
    void* _pthread_cond;      /* pthread_cond_t */
    int   _is_initialized;
} ainos_platform_cond_t;
#endif

/* ---------- 4.4 线程 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_thread {
    void* _handle;            /* HANDLE */
    unsigned long _id;        /* DWORD thread ID */
    int   _is_valid;
    void* _stack_base;        /* 线程栈基址 (调试用) */
} ainos_platform_thread_t;
#else
typedef struct ainos_platform_thread {
    void* _pthread;           /* pthread_t */
    int   _is_valid;
    pid_t _tid;               /* gettid() 保存 */
} ainos_platform_thread_t;
#endif

/* ---------- 4.5 线程本地存储 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_tls {
    unsigned long _index;     /* DWORD Tls index */
    int   _is_allocated;
} ainos_platform_tls_t;
#else
typedef struct ainos_platform_tls {
    void* _pthread_key;       /* pthread_key_t */
    int   _is_allocated;
} ainos_platform_tls_t;
#endif

/* ---------- 4.6 信号量 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_semaphore {
    void* _handle;            /* HANDLE (CreateSemaphore) */
    int   _is_initialized;
} ainos_platform_semaphore_t;
#else
typedef struct ainos_platform_semaphore {
    void* _sem_ptr;           /* sem_t */
    int   _is_initialized;
    int   _is_named;
} ainos_platform_semaphore_t;
#endif

/* ---------- 4.7 Socket ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_socket {
    uintptr_t _fd;            /* SOCKET (UINT_PTR) */
    int       _domain;
    int       _type;
    int       _protocol;
    int       _is_valid;
    int       _is_nonblocking;
} ainos_platform_socket_t;
#else
typedef struct ainos_platform_socket {
    int  _fd;                 /* int file descriptor */
    int  _domain;
    int  _type;
    int  _protocol;
    int  _is_valid;
    int  _is_nonblocking;
} ainos_platform_socket_t;
#endif

/* ---------- 4.8 Socket 地址 ---------- */
typedef struct ainos_platform_sockaddr {
    char     _data[128];      /* 足够容纳 sockaddr_in / sockaddr_in6 / sockaddr_un */
    unsigned _len;
} ainos_platform_sockaddr_t;

/* ---------- 4.9 文件 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_file {
    void* _handle;            /* HANDLE (CreateFile) */
    int   _is_valid;
    int   _access_mode;       /* 打开模式 */
    char  _path[1024];        /* 文件路径 */
} ainos_platform_file_t;
#else
typedef struct ainos_platform_file {
    int  _fd;                 /* int file descriptor */
    int  _is_valid;
    int  _access_mode;
    char _path[1024];
} ainos_platform_file_t;
#endif

/* ---------- 4.10 文件状态 ---------- */
typedef struct ainos_platform_file_stat {
    uint64_t size;            /* 文件大小 (字节) */
    uint64_t created_time;    /* 创建时间 (Unix 时间戳, 毫秒) */
    uint64_t modified_time;   /* 修改时间 (Unix 时间戳, 毫秒) */
    uint64_t accessed_time;   /* 访问时间 (Unix 时间戳, 毫秒) */
    int      is_directory;
    int      is_regular;
    int      is_symlink;
    int      permissions;     /* Unix 权限位或 Windows 文件属性 */
} ainos_platform_file_stat_t;

/* ---------- 4.11 目录迭代器 ---------- */
typedef struct ainos_platform_dir {
    void* _handle;            /* DIR* / HANDLE */
    int   _is_valid;
    char  _path[1024];
    int   _entry_index;
} ainos_platform_dir_t;

typedef struct ainos_platform_dirent {
    char  name[1024];         /* 条目名称 */
    int   is_directory;
    int   is_regular;
    uint64_t size;
} ainos_platform_dirent_t;

/* ---------- 4.12 时间 ---------- */
typedef struct ainos_platform_time {
    int64_t  seconds;         /* Unix 时间戳 (秒, 自 1970-01-01) */
    int64_t  nanoseconds;     /* 纳秒部分 (0-999999999) */
    int64_t  raw_counter;     /* 平台原始计时器值 */
    int64_t  raw_frequency;   /* 平台原始计时器频率 */
} ainos_platform_time_t;

/* ---------- 4.13 时间间隔 ---------- */
typedef struct ainos_platform_duration {
    int64_t seconds;
    int64_t nanoseconds;
} ainos_platform_duration_t;

/* ---------- 4.14 进程 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_process {
    void* _handle;            /* HANDLE (OpenProcess) */
    unsigned long _pid;       /* DWORD process ID */
    int   _is_valid;
    int   _exit_code;
    int   _has_exited;
    void* _thread_handle;    /* 主线程句柄 */
    void* _stdin_pipe;       /* 管道句柄 */
    void* _stdout_pipe;
    void* _stderr_pipe;
} ainos_platform_process_t;
#else
typedef struct ainos_platform_process {
    pid_t _pid;
    int   _is_valid;
    int   _exit_code;
    int   _has_exited;
    int   _stdin_fd;
    int   _stdout_fd;
    int   _stderr_fd;
    int   _waitpid_called;
} ainos_platform_process_t;
#endif

/* ---------- 4.15 动态库 ---------- */
typedef struct ainos_platform_library {
    void* _handle;            /* HMODULE / void* */
    int   _is_valid;
    char  _path[1024];
} ainos_platform_library_t;

/* ---------- 4.16 共享内存 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_shm {
    void* _handle;            /* HANDLE (CreateFileMapping) */
    void* _addr;              /* 映射地址 */
    size_t _size;
    int    _is_valid;
    char   _name[256];
} ainos_platform_shm_t;
#else
typedef struct ainos_platform_shm {
    int    _fd;               /* shm_open fd */
    void*  _addr;             /* mmap 地址 */
    size_t _size;
    int    _is_valid;
    char   _name[256];
} ainos_platform_shm_t;
#endif

/* ---------- 4.17 原子操作 ---------- */
typedef struct ainos_platform_atomic32 {
    volatile int32_t _value;
} ainos_platform_atomic32_t;

typedef struct ainos_platform_atomic64 {
    volatile int64_t _value;
} ainos_platform_atomic64_t;

/* ---------- 4.18 线程池 ---------- */
typedef struct ainos_platform_threadpool ainos_platform_threadpool_t;

/* ---------- 4.19 事件 (手动重置/自动重置) ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_event {
    void* _handle;            /* HANDLE (CreateEvent) */
    int   _is_initialized;
    int   _is_manual_reset;
} ainos_platform_event_t;
#else
typedef struct ainos_platform_event {
    void*  _cond;             /* pthread_cond_t */
    void*  _mutex;            /* pthread_mutex_t */
    int    _is_initialized;
    int    _is_manual_reset;
    int    _signaled;
} ainos_platform_event_t;
#endif

/* ---------- 4.20 屏障 ---------- */
#if AINOS_PLATFORM_WIN32
typedef struct ainos_platform_barrier {
    void* _barrier;           /* 模拟实现 */
    int   _is_initialized;
    int   _count;
    int   _waiters;
    void* _mutex;
    void* _event;
} ainos_platform_barrier_t;
#else
typedef struct ainos_platform_barrier {
    void* _pthread_barrier;   /* pthread_barrier_t */
    int   _is_initialized;
} ainos_platform_barrier_t;
#endif

/* ================================================================
 * 5. 平台初始化和清理
 * ================================================================
 * 在使用任何平台 API 前必须调用 ainos_platform_init()。
 * 程序退出前应调用 ainos_platform_cleanup()。
 */

/* 初始化平台子系统 (Winsock, 线程池等)
 * 返回 0 成功, 负值错误码 */
int ainos_platform_init(void);

/* 清理平台子系统 (WSACleanup 等) */
void ainos_platform_cleanup(void);

/* 检查平台是否已初始化 */
int ainos_platform_is_initialized(void);

/* 获取平台名称字符串 ("windows", "linux", "darwin") */
const char* ainos_platform_name(void);

/* 获取平台版本字符串 */
const char* ainos_platform_version(void);

/* ================================================================
 * 6. 互斥锁 (Mutex) API
 * ================================================================ */

/* 互斥锁类型 */
#define AINOS_PLATFORM_MUTEX_NORMAL      0
#define AINOS_PLATFORM_MUTEX_RECURSIVE   1
#define AINOS_PLATFORM_MUTEX_ERRORCHECK  2

/* 初始化互斥锁
 * type: AINOS_PLATFORM_MUTEX_NORMAL / RECURSIVE / ERRORCHECK
 * 返回 0 成功 */
int ainos_platform_mutex_init(ainos_platform_mutex_t* mutex, int type);

/* 销毁互斥锁 */
int ainos_platform_mutex_destroy(ainos_platform_mutex_t* mutex);

/* 加锁 (阻塞) */
int ainos_platform_mutex_lock(ainos_platform_mutex_t* mutex);

/* 尝试加锁 (非阻塞)
 * 返回 0 成功, AINOS_PLATFORM_ERR_BUSY 已被锁 */
int ainos_platform_mutex_trylock(ainos_platform_mutex_t* mutex);

/* 解锁 */
int ainos_platform_mutex_unlock(ainos_platform_mutex_t* mutex);

/* 带超时的加锁 (毫秒)
 * 返回 0 成功, AINOS_PLATFORM_ERR_TIMEOUT 超时 */
int ainos_platform_mutex_lock_timeout(ainos_platform_mutex_t* mutex,
                                      int timeout_ms);

/* 检查互斥锁是否已初始化 */
int ainos_platform_mutex_is_valid(const ainos_platform_mutex_t* mutex);

/* ================================================================
 * 7. 读写锁 (RWLock) API
 * ================================================================ */

/* 初始化读写锁 */
int ainos_platform_rwlock_init(ainos_platform_rwlock_t* rwlock);

/* 销毁读写锁 */
int ainos_platform_rwlock_destroy(ainos_platform_rwlock_t* rwlock);

/* 获取读锁 (共享) */
int ainos_platform_rwlock_rdlock(ainos_platform_rwlock_t* rwlock);

/* 尝试获取读锁 */
int ainos_platform_rwlock_try_rdlock(ainos_platform_rwlock_t* rwlock);

/* 获取写锁 (独占) */
int ainos_platform_rwlock_wrlock(ainos_platform_rwlock_t* rwlock);

/* 尝试获取写锁 */
int ainos_platform_rwlock_try_wrlock(ainos_platform_rwlock_t* rwlock);

/* 解锁读写锁 */
int ainos_platform_rwlock_unlock(ainos_platform_rwlock_t* rwlock);

/* ================================================================
 * 8. 条件变量 (Condition Variable) API
 * ================================================================ */

/* 初始化条件变量 */
int ainos_platform_cond_init(ainos_platform_cond_t* cond);

/* 销毁条件变量 */
int ainos_platform_cond_destroy(ainos_platform_cond_t* cond);

/* 等待条件变量 (必须已持有 mutex)
 * 返回 0 成功, AINOS_PLATFORM_ERR_TIMEOUT 超时 */
int ainos_platform_cond_wait(ainos_platform_cond_t* cond,
                             ainos_platform_mutex_t* mutex);

/* 带超时的等待 (毫秒) */
int ainos_platform_cond_timedwait(ainos_platform_cond_t* cond,
                                  ainos_platform_mutex_t* mutex,
                                  int timeout_ms);

/* 唤醒一个等待线程 */
int ainos_platform_cond_signal(ainos_platform_cond_t* cond);

/* 唤醒所有等待线程 */
int ainos_platform_cond_broadcast(ainos_platform_cond_t* cond);

/* ================================================================
 * 9. 信号量 (Semaphore) API
 * ================================================================ */

/* 初始化信号量
 * initial_value: 初始计数值
 * max_value: 最大值 (0 = 无限制) */
int ainos_platform_sem_init(ainos_platform_semaphore_t* sem,
                            unsigned int initial_value,
                            unsigned int max_value);

/* 销毁信号量 */
int ainos_platform_sem_destroy(ainos_platform_semaphore_t* sem);

/* 等待 (P 操作, 递减) */
int ainos_platform_sem_wait(ainos_platform_semaphore_t* sem);

/* 尝试等待 (非阻塞) */
int ainos_platform_sem_trywait(ainos_platform_semaphore_t* sem);

/* 带超时的等待 (毫秒) */
int ainos_platform_sem_timedwait(ainos_platform_semaphore_t* sem,
                                 int timeout_ms);

/* 发信号 (V 操作, 递增) */
int ainos_platform_sem_post(ainos_platform_semaphore_t* sem);

/* 获取当前值 */
int ainos_platform_sem_getvalue(ainos_platform_semaphore_t* sem,
                                int* value);

/* ================================================================
 * 10. 事件 (Event) API
 * ================================================================ */

/* 初始化事件对象
 * manual_reset: 1 = 手动重置, 0 = 自动重置
 * initial_state: 1 = 有信号, 0 = 无信号 */
int ainos_platform_event_init(ainos_platform_event_t* event,
                              int manual_reset, int initial_state);

/* 销毁事件对象 */
int ainos_platform_event_destroy(ainos_platform_event_t* event);

/* 等待事件变为有信号 */
int ainos_platform_event_wait(ainos_platform_event_t* event);

/* 带超时等待 (毫秒) */
int ainos_platform_event_timedwait(ainos_platform_event_t* event,
                                   int timeout_ms);

/* 设置事件为有信号状态 */
int ainos_platform_event_set(ainos_platform_event_t* event);

/* 重置事件为无信号状态 */
int ainos_platform_event_reset(ainos_platform_event_t* event);

/* 脉冲事件 (自动唤醒后复位) */
int ainos_platform_event_pulse(ainos_platform_event_t* event);

/* ================================================================
 * 11. 屏障 (Barrier) API
 * ================================================================ */

/* 初始化屏障
 * count: 需要等待的线程数 */
int ainos_platform_barrier_init(ainos_platform_barrier_t* barrier,
                                int count);

/* 销毁屏障 */
int ainos_platform_barrier_destroy(ainos_platform_barrier_t* barrier);

/* 等待屏障 (阻塞直到 count 个线程到达) */
int ainos_platform_barrier_wait(ainos_platform_barrier_t* barrier);

/* ================================================================
 * 12. 线程 (Thread) API
 * ================================================================ */

/* 线程入口函数类型 */
typedef int (*ainos_platform_thread_func_t)(void* arg);

/* 线程优先级 */
#define AINOS_PLATFORM_THREAD_PRIO_LOWEST     0
#define AINOS_PLATFORM_THREAD_PRIO_LOW        1
#define AINOS_PLATFORM_THREAD_PRIO_NORMAL     2
#define AINOS_PLATFORM_THREAD_PRIO_HIGH       3
#define AINOS_PLATFORM_THREAD_PRIO_HIGHEST    4
#define AINOS_PLATFORM_THREAD_PRIO_TIME_CRITICAL 5

/* 线程创建属性 */
typedef struct ainos_platform_thread_attr {
    size_t stack_size;           /* 栈大小 (0 = 默认) */
    int    priority;             /* 优先级 */
    int    is_detached;          /* 1 = 分离线程 (自动回收) */
    char   name[64];             /* 线程名称 (调试用) */
    int    affinity;             /* CPU 亲和性 (-1 = 不设置) */
} ainos_platform_thread_attr_t;

#define AINOS_PLATFORM_THREAD_ATTR_DEFAULT \
    { 0, AINOS_PLATFORM_THREAD_PRIO_NORMAL, 0, "", -1 }

/* 创建线程
 * thread: 输出参数, 填充线程句柄
 * attr: 线程属性, 传 NULL 使用默认值
 * func: 入口函数
 * arg: 入口函数参数
 * 返回 0 成功 */
int ainos_platform_thread_create(ainos_platform_thread_t* thread,
                                 const ainos_platform_thread_attr_t* attr,
                                 ainos_platform_thread_func_t func,
                                 void* arg);

/* 等待线程结束
 * exit_code: 输出参数, 接收线程返回值 (可传 NULL) */
int ainos_platform_thread_join(ainos_platform_thread_t* thread,
                               int* exit_code);

/* 分离线程 (线程结束后自动回收资源) */
int ainos_platform_thread_detach(ainos_platform_thread_t* thread);

/* 获取当前线程的 ID */
unsigned long long ainos_platform_thread_self_id(void);

/* 获取当前线程名称 (写入 name, 最多 name_size 字节) */
int ainos_platform_thread_get_name(char* name, size_t name_size);

/* 设置当前线程名称 */
int ainos_platform_thread_set_name(const char* name);

/* 让出 CPU 时间片 */
void ainos_platform_thread_yield(void);

/* 线程睡眠 (毫秒) */
int ainos_platform_thread_sleep(int milliseconds);

/* 检查线程是否仍在运行
 * 返回 1 运行中, 0 已终止, 负值错误 */
int ainos_platform_thread_is_running(ainos_platform_thread_t* thread);

/* 获取线程的 CPU 时间 (用户态+内核态, 纳秒) */
int ainos_platform_thread_get_cpu_time(ainos_platform_thread_t* thread,
                                       uint64_t* user_ns,
                                       uint64_t* kernel_ns);

/* ================================================================
 * 13. 线程本地存储 (TLS) API
 * ================================================================ */

/* 分配 TLS 键 */
int ainos_platform_tls_alloc(ainos_platform_tls_t* tls);

/* 释放 TLS 键 */
int ainos_platform_tls_free(ainos_platform_tls_t* tls);

/* 设置 TLS 值 */
int ainos_platform_tls_set(ainos_platform_tls_t* tls, void* value);

/* 获取 TLS 值 */
void* ainos_platform_tls_get(ainos_platform_tls_t* tls);

/* ================================================================
 * 14. 线程池 (Thread Pool) API
 * ================================================================ */

/* 线程池任务函数 */
typedef void (*ainos_platform_threadpool_work_func_t)(void* arg);

/* 线程池配置 */
typedef struct ainos_platform_threadpool_config {
    int min_threads;           /* 最小线程数 */
    int max_threads;           /* 最大线程数 */
    int keepalive_ms;          /* 空闲线程保持时间 (毫秒) */
    int queue_depth;           /* 任务队列最大深度 (0 = 无限制) */
    char name[64];             /* 线程池名称 */
} ainos_platform_threadpool_config_t;

#define AINOS_PLATFORM_THREADPOOL_CONFIG_DEFAULT \
    { 2, 8, 60000, 0, "" }

/* 创建线程池 */
int ainos_platform_threadpool_create(
    ainos_platform_threadpool_t** pool,
    const ainos_platform_threadpool_config_t* config);

/* 提交任务到线程池
 * 返回 0 成功, AINOS_PLATFORM_ERR_AGAIN 队列满 */
int ainos_platform_threadpool_submit(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_work_func_t func,
    void* arg);

/* 等待所有任务完成 */
int ainos_platform_threadpool_wait(ainos_platform_threadpool_t* pool);

/* 获取线程池统计 */
typedef struct ainos_platform_threadpool_stats {
    int active_threads;        /* 活跃线程数 */
    int idle_threads;          /* 空闲线程数 */
    int pending_tasks;         /* 待处理任务数 */
    int completed_tasks;       /* 已完成任务数 */
    int rejected_tasks;        /* 被拒绝任务数 */
    int total_threads;         /* 总线程数 */
} ainos_platform_threadpool_stats_t;

int ainos_platform_threadpool_get_stats(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_stats_t* stats);

/* 销毁线程池 (等待所有任务完成) */
int ainos_platform_threadpool_destroy(
    ainos_platform_threadpool_t* pool);

/* ================================================================
 * 15. Socket API
 * ================================================================ */

/* Socket 地址族 */
#define AINOS_PLATFORM_AF_UNSPEC   0
#define AINOS_PLATFORM_AF_INET     2
#define AINOS_PLATFORM_AF_INET6    23
#define AINOS_PLATFORM_AF_UNIX     1

/* Socket 类型 */
#define AINOS_PLATFORM_SOCK_STREAM    1
#define AINOS_PLATFORM_SOCK_DGRAM     2
#define AINOS_PLATFORM_SOCK_RAW       3

/* Socket 协议 */
#define AINOS_PLATFORM_IPPROTO_TCP    6
#define AINOS_PLATFORM_IPPROTO_UDP    17
#define AINOS_PLATFORM_IPPROTO_ICMP   1

/* Socket 关闭方向 */
#define AINOS_PLATFORM_SHUT_RD        0
#define AINOS_PLATFORM_SHUT_WR        1
#define AINOS_PLATFORM_SHUT_RDWR      2

/* Socket 选项级别 */
#define AINOS_PLATFORM_SOL_SOCKET     1
#define AINOS_PLATFORM_SOL_TCP        6

/* Socket 选项 */
#define AINOS_PLATFORM_SO_REUSEADDR   2
#define AINOS_PLATFORM_SO_KEEPALIVE   8
#define AINOS_PLATFORM_SO_LINGER      13
#define AINOS_PLATFORM_SO_RCVBUF      8
#define AINOS_PLATFORM_SO_SNDBUF      7
#define AINOS_PLATFORM_SO_RCVTIMEO    20
#define AINOS_PLATFORM_SO_SNDTIMEO    21
#define AINOS_PLATFORM_TCP_NODELAY    1

/* IP 地址字符串最大长度 */
#define AINOS_PLATFORM_INET_ADDRSTRLEN  16
#define AINOS_PLATFORM_INET6_ADDRSTRLEN 46

/* 创建 Socket
 * domain: AF_INET / AF_INET6 / AF_UNIX
 * type: SOCK_STREAM / SOCK_DGRAM
 * protocol: 0 (自动) 或 IPPROTO_TCP / IPPROTO_UDP
 * 返回 0 成功, socket 句柄通过 sock 返回 */
int ainos_platform_socket_create(ainos_platform_socket_t* sock,
                                 int domain, int type, int protocol);

/* 关闭 Socket */
int ainos_platform_socket_close(ainos_platform_socket_t* sock);

/* 关闭 Socket 的收发方向 */
int ainos_platform_socket_shutdown(ainos_platform_socket_t* sock,
                                   int how);

/* 绑定地址 */
int ainos_platform_socket_bind(ainos_platform_socket_t* sock,
                               const ainos_platform_sockaddr_t* addr);

/* 监听 (仅 SOCK_STREAM) */
int ainos_platform_socket_listen(ainos_platform_socket_t* sock,
                                 int backlog);

/* 接受连接
 * client_addr: 输出参数, 客户地址 (可传 NULL) */
int ainos_platform_socket_accept(ainos_platform_socket_t* sock,
                                 ainos_platform_socket_t* client_sock,
                                 ainos_platform_sockaddr_t* client_addr);

/* 连接远程地址 */
int ainos_platform_socket_connect(ainos_platform_socket_t* sock,
                                  const ainos_platform_sockaddr_t* addr);

/* 发送数据
 * 返回实际发送字节数, 负值错误 */
int ainos_platform_socket_send(ainos_platform_socket_t* sock,
                               const void* data, int len, int flags);

/* 接收数据
 * 返回实际接收字节数, 0 连接关闭, 负值错误 */
int ainos_platform_socket_recv(ainos_platform_socket_t* sock,
                               void* buf, int len, int flags);

/* 发送数据到指定地址 (UDP) */
int ainos_platform_socket_sendto(ainos_platform_socket_t* sock,
                                 const void* data, int len, int flags,
                                 const ainos_platform_sockaddr_t* dest_addr);

/* 从指定地址接收数据 (UDP) */
int ainos_platform_socket_recvfrom(ainos_platform_socket_t* sock,
                                   void* buf, int len, int flags,
                                   ainos_platform_sockaddr_t* src_addr);

/* 设置非阻塞模式 */
int ainos_platform_socket_set_nonblocking(ainos_platform_socket_t* sock,
                                          int nonblocking);

/* 设置 Socket 选项 */
int ainos_platform_socket_set_option(ainos_platform_socket_t* sock,
                                     int level, int optname,
                                     const void* optval, int optlen);

/* 获取 Socket 选项 */
int ainos_platform_socket_get_option(ainos_platform_socket_t* sock,
                                     int level, int optname,
                                     void* optval, int* optlen);

/* 获取本端地址 */
int ainos_platform_socket_get_local_addr(
    ainos_platform_socket_t* sock,
    ainos_platform_sockaddr_t* addr);

/* 获取对端地址 */
int ainos_platform_socket_get_peer_addr(
    ainos_platform_socket_t* sock,
    ainos_platform_sockaddr_t* addr);

/* 检查 Socket 是否有效 */
int ainos_platform_socket_is_valid(
    const ainos_platform_socket_t* sock);

/* Socket 多路复用 (select 风格) */
#define AINOS_PLATFORM_SOCKET_POLLIN  1
#define AINOS_PLATFORM_SOCKET_POLLOUT 2
#define AINOS_PLATFORM_SOCKET_POLLERR 4

typedef struct ainos_platform_pollfd {
    ainos_platform_socket_t* sock;
    int events;             /* 感兴趣的事件 */
    int revents;            /* 返回的事件 */
} ainos_platform_pollfd_t;

int ainos_platform_socket_poll(ainos_platform_pollfd_t* fds,
                               int nfds, int timeout_ms);

/* ================================================================
 * 16. Socket 地址构造 API
 * ================================================================ */

/* 构造 IPv4 地址
 * addr: 输出参数
 * ip: "192.168.1.1" 格式字符串
 * port: 端口号 (主机字节序) */
int ainos_platform_sockaddr_set_inet4(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port);

/* 构造 IPv6 地址 */
int ainos_platform_sockaddr_set_inet6(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port);

/* 构造 Unix Domain Socket 地址 */
int ainos_platform_sockaddr_set_unix(ainos_platform_sockaddr_t* addr,
                                     const char* path);

/* 获取地址族 */
int ainos_platform_sockaddr_get_family(
    const ainos_platform_sockaddr_t* addr);

/* 获取 IP 地址字符串和端口 */
int ainos_platform_sockaddr_get_inet4(
    const ainos_platform_sockaddr_t* addr,
    char* ip, int ip_len, uint16_t* port);

int ainos_platform_sockaddr_get_inet6(
    const ainos_platform_sockaddr_t* addr,
    char* ip, int ip_len, uint16_t* port);

/* DNS 解析
 * hostname: 主机名
 * addr: 输出参数数组
 * addr_count: 输入为 addr 数组大小, 输出为实际地址数量
 * 返回 0 成功, 负值错误 */
int ainos_platform_dns_resolve(const char* hostname,
                               ainos_platform_sockaddr_t* addrs,
                               int* addr_count);

/* ================================================================
 * 17. 文件 I/O API
 * ================================================================ */

/* 文件打开模式 */
#define AINOS_PLATFORM_FILE_O_RDONLY    0x0001
#define AINOS_PLATFORM_FILE_O_WRONLY    0x0002
#define AINOS_PLATFORM_FILE_O_RDWR      0x0004
#define AINOS_PLATFORM_FILE_O_CREAT     0x0008
#define AINOS_PLATFORM_FILE_O_TRUNC     0x0010
#define AINOS_PLATFORM_FILE_O_APPEND    0x0020
#define AINOS_PLATFORM_FILE_O_EXCL      0x0040
#define AINOS_PLATFORM_FILE_O_SYNC      0x0080
#define AINOS_PLATFORM_FILE_O_DIRECTORY 0x0100
#define AINOS_PLATFORM_FILE_O_TEMPORARY 0x0200  /* Windows: 临时文件 */

/* 文件权限 (Unix 风格, Windows 酌情映射) */
#define AINOS_PLATFORM_FILE_PERM_DEFAULT 0644
#define AINOS_PLATFORM_FILE_PERM_EXEC    0755

/* 文件 seek 起始位置 */
#define AINOS_PLATFORM_FILE_SEEK_SET     0
#define AINOS_PLATFORM_FILE_SEEK_CUR     1
#define AINOS_PLATFORM_FILE_SEEK_END     2

/* 打开文件
 * path: 文件路径
 * flags: 打开模式 (AINOS_PLATFORM_FILE_O_* 位或)
 * mode: 创建时的权限 (仅在 O_CREAT 时有效, 可传 0)
 * 返回 0 成功 */
int ainos_platform_file_open(ainos_platform_file_t* file,
                             const char* path, int flags, int mode);

/* 关闭文件 */
int ainos_platform_file_close(ainos_platform_file_t* file);

/* 读取文件
 * 返回实际读取字节数, 0 文件尾, 负值错误 */
int64_t ainos_platform_file_read(ainos_platform_file_t* file,
                                 void* buf, int64_t count);

/* 写入文件
 * 返回实际写入字节数, 负值错误 */
int64_t ainos_platform_file_write(ainos_platform_file_t* file,
                                  const void* buf, int64_t count);

/* 移动文件读写位置
 * offset: 偏移量
 * whence: SEEK_SET / SEEK_CUR / SEEK_END
 * 返回 0 成功 */
int ainos_platform_file_seek(ainos_platform_file_t* file,
                             int64_t offset, int whence);

/* 获取当前读写位置 */
int64_t ainos_platform_file_tell(ainos_platform_file_t* file);

/* 获取文件状态 */
int ainos_platform_file_stat(const char* path,
                             ainos_platform_file_stat_t* stat);

/* 获取已打开文件的状态 */
int ainos_platform_file_fstat(ainos_platform_file_t* file,
                              ainos_platform_file_stat_t* stat);

/* 删除文件 */
int ainos_platform_file_unlink(const char* path);

/* 重命名文件 */
int ainos_platform_file_rename(const char* old_path,
                               const char* new_path);

/* 复制文件 */
int ainos_platform_file_copy(const char* src, const char* dst);

/* 截断/扩展文件 */
int ainos_platform_file_truncate(ainos_platform_file_t* file,
                                 int64_t length);

/* 刷新文件缓冲区到磁盘 */
int ainos_platform_file_sync(ainos_platform_file_t* file);

/* 检查文件是否存在 */
int ainos_platform_file_exists(const char* path);

/* 获取文件权限字符串 (如 "rwxr-xr-x") */
int ainos_platform_file_permissions_string(int mode, char* buf,
                                           size_t buf_size);

/* ================================================================
 * 18. 目录操作 API
 * ================================================================ */

/* 打开目录 */
int ainos_platform_dir_open(ainos_platform_dir_t* dir, const char* path);

/* 读取目录条目
 * 返回 1 成功读取, 0 无更多条目, 负值错误 */
int ainos_platform_dir_read(ainos_platform_dir_t* dir,
                            ainos_platform_dirent_t* entry);

/* 关闭目录 */
int ainos_platform_dir_close(ainos_platform_dir_t* dir);

/* 创建目录 */
int ainos_platform_dir_mkdir(const char* path, int mode);

/* 递归创建目录 (mkdir -p) */
int ainos_platform_dir_mkdir_p(const char* path, int mode);

/* 删除目录 (必须为空) */
int ainos_platform_dir_rmdir(const char* path);

/* 递归删除目录 (rm -rf) */
int ainos_platform_dir_rmdir_r(const char* path);

/* 获取当前工作目录 */
int ainos_platform_dir_getcwd(char* buf, size_t buf_size);

/* 设置当前工作目录 */
int ainos_platform_dir_chdir(const char* path);

/* ================================================================
 * 19. 内存管理 API
 * ================================================================ */

/* 分配内存 (相当于 malloc)
 * 返回非 NULL 成功, NULL 失败 */
void* ainos_platform_mem_alloc(size_t size);

/* 分配并清零内存 (相当于 calloc) */
void* ainos_platform_mem_calloc(size_t num, size_t size);

/* 重新分配内存 (相当于 realloc) */
void* ainos_platform_mem_realloc(void* ptr, size_t new_size);

/* 释放内存 */
void ainos_platform_mem_free(void* ptr);

/* 分配对齐内存
 * alignment: 对齐字节数 (必须是 2 的幂, 且至少为 sizeof(void*))
 * size: 分配大小
 * 返回对齐后的地址, NULL 失败 */
void* ainos_platform_mem_aligned_alloc(size_t alignment, size_t size);

/* 释放对齐内存 */
void ainos_platform_mem_aligned_free(void* ptr);

/* 获取页面大小 */
int ainos_platform_mem_get_page_size(void);

/* 获取系统可用内存 (字节) */
int64_t ainos_platform_mem_get_available_memory(void);

/* 获取系统总物理内存 (字节) */
int64_t ainos_platform_mem_get_total_physical_memory(void);

/* 获取当前进程内存使用 (字节) */
int64_t ainos_platform_mem_get_process_memory(void);

/* 内存拷贝 (保证不重叠时使用 memcpy, 否则用 memmove) */
void* ainos_platform_mem_copy(void* dest, const void* src, size_t n);

/* 内存移动 (处理重叠) */
void* ainos_platform_mem_move(void* dest, const void* src, size_t n);

/* 内存设置 */
void* ainos_platform_mem_set(void* dest, int value, size_t n);

/* 内存比较 */
int ainos_platform_mem_compare(const void* a, const void* b, size_t n);

/* 内存加锁 (防止被换出, 如 mlock/VirtualLock) */
int ainos_platform_mem_lock(const void* addr, size_t size);

/* 内存解锁 */
int ainos_platform_mem_unlock(const void* addr, size_t size);

/* ================================================================
 * 20. 共享内存 API
 * ================================================================ */

/* 创建或打开共享内存
 * name: 共享内存名称 (平台相关: Linux 以 / 开头)
 * size: 大小
 * create: 1 = 创建, 0 = 打开已有
 * 返回 0 成功 */
int ainos_platform_shm_create(ainos_platform_shm_t* shm,
                              const char* name, size_t size, int create);

/* 映射共享内存到进程地址空间 */
int ainos_platform_shm_map(ainos_platform_shm_t* shm);

/* 取消映射共享内存 */
int ainos_platform_shm_unmap(ainos_platform_shm_t* shm);

/* 关闭共享内存 */
int ainos_platform_shm_close(ainos_platform_shm_t* shm);

/* 删除共享内存 */
int ainos_platform_shm_unlink(const char* name);

/* 获取共享内存地址 */
void* ainos_platform_shm_get_addr(const ainos_platform_shm_t* shm);

/* 获取共享内存大小 */
size_t ainos_platform_shm_get_size(const ainos_platform_shm_t* shm);

/* ================================================================
 * 21. 原子操作 API
 * ================================================================ */

/* 初始化原子变量 */
void ainos_platform_atomic32_init(ainos_platform_atomic32_t* atomic,
                                  int32_t value);
void ainos_platform_atomic64_init(ainos_platform_atomic64_t* atomic,
                                  int64_t value);

/* 原子加载 */
int32_t ainos_platform_atomic32_load(ainos_platform_atomic32_t* atomic);
int64_t ainos_platform_atomic64_load(ainos_platform_atomic64_t* atomic);

/* 原子存储 */
void ainos_platform_atomic32_store(ainos_platform_atomic32_t* atomic,
                                   int32_t value);
void ainos_platform_atomic64_store(ainos_platform_atomic64_t* atomic,
                                   int64_t value);

/* 原子交换 */
int32_t ainos_platform_atomic32_exchange(ainos_platform_atomic32_t* atomic,
                                         int32_t value);
int64_t ainos_platform_atomic64_exchange(ainos_platform_atomic64_t* atomic,
                                         int64_t value);

/* 比较并交换 (CAS)
 * 返回旧值 */
int32_t ainos_platform_atomic32_compare_exchange(
    ainos_platform_atomic32_t* atomic, int32_t expected, int32_t desired);
int64_t ainos_platform_atomic64_compare_exchange(
    ainos_platform_atomic64_t* atomic, int64_t expected, int64_t desired);

/* 原子加法 (返回新值) */
int32_t ainos_platform_atomic32_fetch_add(
    ainos_platform_atomic32_t* atomic, int32_t value);
int64_t ainos_platform_atomic64_fetch_add(
    ainos_platform_atomic64_t* atomic, int64_t value);

/* 原子减法 (返回新值) */
int32_t ainos_platform_atomic32_fetch_sub(
    ainos_platform_atomic32_t* atomic, int32_t value);
int64_t ainos_platform_atomic64_fetch_sub(
    ainos_platform_atomic64_t* atomic, int64_t value);

/* 原子位与/或/异或 */
int32_t ainos_platform_atomic32_fetch_and(
    ainos_platform_atomic32_t* atomic, int32_t value);
int32_t ainos_platform_atomic32_fetch_or(
    ainos_platform_atomic32_t* atomic, int32_t value);
int32_t ainos_platform_atomic32_fetch_xor(
    ainos_platform_atomic32_t* atomic, int32_t value);

/* ================================================================
 * 22. 时间 API
 * ================================================================ */

/* 获取当前时间
 * 返回 0 成功 */
int ainos_platform_time_now(ainos_platform_time_t* t);

/* 获取当前 Unix 时间戳 (毫秒) */
int64_t ainos_platform_time_now_ms(void);

/* 获取单调递增时间 (不受系统时间调整影响, 纳秒) */
int64_t ainos_platform_time_monotonic_ns(void);

/* 获取高精度计时器值 */
int ainos_platform_time_get_raw_counter(int64_t* value);

/* 获取高精度计时器频率 */
int ainos_platform_time_get_raw_frequency(int64_t* frequency);

/* 睡眠指定毫秒数 */
int ainos_platform_time_sleep_ms(int milliseconds);

/* 睡眠指定微秒数 */
int ainos_platform_time_sleep_us(int microseconds);

/* 睡眠指定纳秒数 */
int ainos_platform_time_sleep_ns(int64_t nanoseconds);

/* 获取系统运行时间 (毫秒) */
int64_t ainos_platform_time_get_tick_count(void);

/* 格式化时间为字符串
 * fmt: strftime 格式字符串 (如 "%Y-%m-%d %H:%M:%S")
 * buf: 输出缓冲区
 * buf_size: 缓冲区大小
 * 返回 0 成功 */
int ainos_platform_time_format(const ainos_platform_time_t* t,
                               const char* fmt, char* buf, size_t buf_size);

/* 获取当前时间字符串 (ISO 8601 格式: "2024-01-15T10:30:00.000Z") */
int ainos_platform_time_format_iso8601(char* buf, size_t buf_size);

/* 时间差值 (t1 - t2, 返回纳秒) */
int64_t ainos_platform_time_diff_ns(const ainos_platform_time_t* t1,
                                    const ainos_platform_time_t* t2);

/* 时间差值 (毫秒) */
int64_t ainos_platform_time_diff_ms(const ainos_platform_time_t* t1,
                                    const ainos_platform_time_t* t2);

/* 时间加法 */
void ainos_platform_time_add(ainos_platform_time_t* result,
                             const ainos_platform_time_t* t,
                             const ainos_platform_duration_t* d);

/* 时间减法 */
void ainos_platform_time_sub(ainos_platform_time_t* result,
                             const ainos_platform_time_t* t,
                             const ainos_platform_duration_t* d);

/* 时间比较: -1 t1 < t2, 0 相等, 1 t1 > t2 */
int ainos_platform_time_compare(const ainos_platform_time_t* t1,
                                const ainos_platform_time_t* t2);

/* 从秒+纳秒构造时间 */
void ainos_platform_time_from_unix(ainos_platform_time_t* t,
                                   int64_t seconds, int64_t nanoseconds);

/* ================================================================
 * 23. 进程管理 API
 * ================================================================ */

/* 进程创建标志 */
#define AINOS_PLATFORM_PROCESS_DETACHED     0x0001  /* 分离进程 (不等待) */
#define AINOS_PLATFORM_PROCESS_NEW_CONSOLE  0x0002  /* 新控制台窗口 */
#define AINOS_PLATFORM_PROCESS_SEARCH_PATH  0x0004  /* 在 PATH 中搜索 */
#define AINOS_PLATFORM_PROCESS_REDIRECT_STDIO 0x0008 /* 重定向 stdin/stdout/stderr */
#define AINOS_PLATFORM_PROCESS_LOW_PRIORITY 0x0010  /* 低优先级 */
#define AINOS_PLATFORM_PROCESS_HIGH_PRIORITY 0x0020 /* 高优先级 */
#define AINOS_PLATFORM_PROCESS_NEW_PGROUP   0x0040  /* 新进程组 (Unix) */

/* 启动进程
 * path: 可执行文件路径
 * argv: 参数数组 (以 NULL 结尾)
 * flags: AINOS_PLATFORM_PROCESS_* 组合
 * process: 输出参数
 * 返回 0 成功 */
int ainos_platform_process_spawn(ainos_platform_process_t* process,
                                 const char* path,
                                 char* const argv[],
                                 int flags);

/* 等待进程结束
 * 返回 0 成功, exit_code 输出退出码 */
int ainos_platform_process_wait(ainos_platform_process_t* process,
                                int* exit_code);

/* 等待进程结束 (超时版本)
 * timeout_ms: 超时毫秒数 (0 = 立即检查, -1 = 无限等待) */
int ainos_platform_process_wait_timeout(ainos_platform_process_t* process,
                                        int* exit_code, int timeout_ms);

/* 终止进程 */
int ainos_platform_process_kill(ainos_platform_process_t* process);

/* 获取进程 ID */
int ainos_platform_process_get_pid(void);

/* 获取进程名 */
int ainos_platform_process_get_name(char* name, size_t name_size);

/* 获取进程路径 */
int ainos_platform_process_get_path(char* path, size_t path_size);

/* 检查进程是否在运行 */
int ainos_platform_process_is_running(ainos_platform_process_t* process);

/* 向进程发送信号 (Unix: signal, Windows: TerminateProcess)
 * signal: 信号编号 (平台相关) */
int ainos_platform_process_signal(ainos_platform_process_t* process,
                                  int signal);

/* 枚举系统进程
 * callback: 回调函数, 返回 0 继续, 非 0 停止
 * arg: 回调参数 */
typedef int (*ainos_platform_process_enum_cb_t)(int pid,
                                                 const char* name,
                                                 void* arg);
int ainos_platform_process_enum(
    ainos_platform_process_enum_cb_t callback, void* arg);

/* 获取进程退出码 */
int ainos_platform_process_get_exit_code(
    ainos_platform_process_t* process, int* exit_code);

/* 释放进程资源 (不终止进程) */
int ainos_platform_process_destroy(ainos_platform_process_t* process);

/* ================================================================
 * 24. 动态库加载 API
 * ================================================================ */

/* 加载动态库
 * path: 库文件路径
 * 返回 0 成功 */
int ainos_platform_dlopen(ainos_platform_library_t* lib,
                          const char* path);

/* 获取符号地址
 * 返回非 NULL 成功, NULL 失败 */
void* ainos_platform_dlsym(ainos_platform_library_t* lib,
                           const char* symbol);

/* 关闭动态库 */
int ainos_platform_dlclose(ainos_platform_library_t* lib);

/* 获取上次动态库操作的错误信息 */
const char* ainos_platform_dlerror(void);

/* 获取当前可执行文件路径 */
int ainos_platform_dlget_self_path(char* buf, size_t buf_size);

/* ================================================================
 * 25. 环境变量 API
 * ================================================================ */

/* 获取环境变量
 * 返回 NULL 不存在 */
const char* ainos_platform_getenv(const char* name);

/* 设置环境变量
 * overwrite: 1 覆盖已有值, 0 不覆盖 */
int ainos_platform_setenv(const char* name, const char* value,
                          int overwrite);

/* 删除环境变量 */
int ainos_platform_unsetenv(const char* name);

/* 获取所有环境变量 (格式: "KEY=VALUE" 每行)
 * buf: 输出缓冲区
 * buf_size: 缓冲区大小
 * 返回实际写入字节数 */
int ainos_platform_get_all_env(char* buf, size_t buf_size);

/* ================================================================
 * 26. 错误处理 API
 * ================================================================ */

/* 获取平台错误码 */
int ainos_platform_get_last_error(void);

/* 将平台错误码转换为平台抽象错误码 */
int ainos_platform_errno_to_platform(int sys_errno);

/* 获取错误描述字符串
 * 线程安全, 返回静态缓冲区或错误码的字符串表示 */
const char* ainos_platform_strerror(int err);

/* 获取最后一次错误的详细描述 */
const char* ainos_platform_get_last_error_string(void);

/* 设置错误码 (用于库内部) */
void ainos_platform_set_last_error(int err);

/* 格式化错误消息到缓冲区 */
int ainos_platform_strerror_r(int err, char* buf, size_t buf_size);

/* ================================================================
 * 27. 系统信息 API
 * ================================================================ */

/* CPU 信息 */
typedef struct ainos_platform_cpu_info {
    char  name[256];           /* CPU 型号名称 */
    int   physical_cores;      /* 物理核心数 */
    int   logical_cores;       /* 逻辑核心数 (含超线程) */
    int   numa_nodes;          /* NUMA 节点数 */
    int   is_64bit;            /* 是否 64 位 */
    int   has_avx;             /* AVX 支持 */
    int   has_avx2;            /* AVX2 支持 */
    int   has_avx512;          /* AVX-512 支持 */
    int   has_neon;            /* NEON 支持 (ARM) */
    int   has_sve;             /* SVE 支持 (ARM) */
    int   cache_line_size;     /* 缓存行大小 */
    int   l1d_cache;           /* L1 数据缓存 (KB) */
    int   l1i_cache;           /* L1 指令缓存 (KB) */
    int   l2_cache;            /* L2 缓存 (KB) */
    int   l3_cache;            /* L3 缓存 (KB) */
    double max_freq_mhz;       /* 最大频率 (MHz) */
} ainos_platform_cpu_info_t;

/* 获取 CPU 信息 */
int ainos_platform_sys_get_cpu_info(ainos_platform_cpu_info_t* info);

/* 获取系统负载信息 */
typedef struct ainos_platform_system_load {
    double load_1m;            /* 1 分钟平均负载 */
    double load_5m;            /* 5 分钟平均负载 */
    double load_15m;           /* 15 分钟平均负载 */
    double cpu_usage_percent;  /* CPU 使用率 (0-100) */
    double memory_usage_percent; /* 内存使用率 (0-100) */
    int64_t total_memory;      /* 总物理内存 (字节) */
    int64_t free_memory;       /* 空闲内存 (字节) */
    int64_t used_memory;       /* 已用内存 (字节) */
    int64_t total_swap;        /* 总交换空间 (字节) */
    int64_t free_swap;         /* 空闲交换空间 (字节) */
} ainos_platform_system_load_t;

/* 获取系统负载信息 */
int ainos_platform_sys_get_load(ainos_platform_system_load_t* load);

/* 获取主机名 */
int ainos_platform_sys_get_hostname(char* buf, size_t buf_size);

/* 获取操作系统名称和版本 */
int ainos_platform_sys_get_os_info(char* os_name, size_t name_size,
                                   char* os_version, size_t ver_size);

/* 获取系统运行时间 (秒) */
int64_t ainos_platform_sys_get_uptime(void);

/* 获取系统时区 */
int ainos_platform_sys_get_timezone(char* buf, size_t buf_size);

/* ================================================================
 * 28. 控制台/终端 API
 * ================================================================ */

/* 终端颜色 */
#define AINOS_PLATFORM_COLOR_RESET       0
#define AINOS_PLATFORM_COLOR_RED         1
#define AINOS_PLATFORM_COLOR_GREEN       2
#define AINOS_PLATFORM_COLOR_YELLOW      3
#define AINOS_PLATFORM_COLOR_BLUE        4
#define AINOS_PLATFORM_COLOR_MAGENTA     5
#define AINOS_PLATFORM_COLOR_CYAN        6
#define AINOS_PLATFORM_COLOR_WHITE       7
#define AINOS_PLATFORM_COLOR_BRIGHT_RED  8
#define AINOS_PLATFORM_COLOR_BRIGHT_GREEN 9
#define AINOS_PLATFORM_COLOR_BRIGHT_YELLOW 10
#define AINOS_PLATFORM_COLOR_BRIGHT_BLUE 11
#define AINOS_PLATFORM_COLOR_BRIGHT_MAGENTA 12
#define AINOS_PLATFORM_COLOR_BRIGHT_CYAN 13
#define AINOS_PLATFORM_COLOR_BRIGHT_WHITE 14

/* 设置终端文本颜色
 * 返回 0 成功 (非终端环境返回错误) */
int ainos_platform_console_set_color(int color);

/* 重置终端颜色 */
int ainos_platform_console_reset_color(void);

/* 获取终端宽度 (列数) */
int ainos_platform_console_get_width(void);

/* 获取终端高度 (行数) */
int ainos_platform_console_get_height(void);

/* 终端是否支持彩色输出 */
int ainos_platform_console_has_color(void);

/* ================================================================
 * 29. 日志 API
 * ================================================================ */

/* 日志级别 */
#define AINOS_PLATFORM_LOG_DEBUG   0
#define AINOS_PLATFORM_LOG_INFO    1
#define AINOS_PLATFORM_LOG_WARN    2
#define AINOS_PLATFORM_LOG_ERROR   3
#define AINOS_PLATFORM_LOG_FATAL   4

/* 日志回调函数类型 */
typedef void (*ainos_platform_log_func_t)(int level, const char* message,
                                          void* user_data);

/* 设置日志回调 */
void ainos_platform_log_set_callback(ainos_platform_log_func_t callback,
                                     void* user_data);

/* 设置日志级别 (低于此级别的不输出) */
void ainos_platform_log_set_level(int level);

/* 输出日志 */
void ainos_platform_log_write(int level, const char* file, int line,
                              const char* func, const char* fmt, ...);

/* 便捷宏 */
#define AINOS_PLATFORM_LOG_DEBUG(fmt, ...) \
    ainos_platform_log_write(AINOS_PLATFORM_LOG_DEBUG, __FILE__, __LINE__, \
                             __func__, fmt, ##__VA_ARGS__)
#define AINOS_PLATFORM_LOG_INFO(fmt, ...) \
    ainos_platform_log_write(AINOS_PLATFORM_LOG_INFO, __FILE__, __LINE__, \
                             __func__, fmt, ##__VA_ARGS__)
#define AINOS_PLATFORM_LOG_WARN(fmt, ...) \
    ainos_platform_log_write(AINOS_PLATFORM_LOG_WARN, __FILE__, __LINE__, \
                             __func__, fmt, ##__VA_ARGS__)
#define AINOS_PLATFORM_LOG_ERROR(fmt, ...) \
    ainos_platform_log_write(AINOS_PLATFORM_LOG_ERROR, __FILE__, __LINE__, \
                             __func__, fmt, ##__VA_ARGS__)

/* ================================================================
 * 30. UUID 生成 API
 * ================================================================ */

/* 生成 UUID v4 (随机)
 * buf: 输出缓冲区 (至少 37 字节)
 * 返回 0 成功 */
int ainos_platform_uuid_v4_generate(char* buf, size_t buf_size);

/* ================================================================
 * 31. 字符串工具 API
 * ================================================================ */

/* 宽字符串到 UTF-8 转换 (Windows 专用, Unix 下为 no-op) */
int ainos_platform_wchar_to_utf8(const wchar_t* wstr, char* buf,
                                 size_t buf_size);

/* UTF-8 到宽字符串转换 */
int ainos_platform_utf8_to_wchar(const char* utf8, wchar_t* buf,
                                 size_t buf_size);

/* 获取本地化错误信息 (Windows FormatMessage, Unix strerror_l) */
int ainos_platform_strerror_locale(int err, char* buf, size_t buf_size,
                                   const char* locale);

/* ================================================================
 * 32. 内联工具函数
 * ================================================================ */

/* 计算最小值和最大值 */
static inline int ainos_platform_min_i(int a, int b)
{
    return a < b ? a : b;
}

static inline int ainos_platform_max_i(int a, int b)
{
    return a > b ? a : b;
}

static inline int64_t ainos_platform_min_i64(int64_t a, int64_t b)
{
    return a < b ? a : b;
}

static inline int64_t ainos_platform_max_i64(int64_t a, int64_t b)
{
    return a > b ? a : b;
}

static inline size_t ainos_platform_min_sz(size_t a, size_t b)
{
    return a < b ? a : b;
}

static inline size_t ainos_platform_max_sz(size_t a, size_t b)
{
    return a > b ? a : b;
}

/* 对齐到上界 */
static inline size_t ainos_platform_align_up(size_t value, size_t alignment)
{
    return (value + alignment - 1) & ~(alignment - 1);
}

/* 对齐到下界 */
static inline size_t ainos_platform_align_down(size_t value, size_t alignment)
{
    return value & ~(alignment - 1);
}

/* 检查是否为 2 的幂 */
static inline int ainos_platform_is_power_of_2(size_t value)
{
    return value && !(value & (value - 1));
}

/* ================================================================
 * 33. 断言和调试
 * ================================================================ */

#ifndef AINOS_PLATFORM_ASSERT
#  include <assert.h>
#  define AINOS_PLATFORM_ASSERT(cond) assert(cond)
#endif

/* 调试断点 */
static inline void ainos_platform_debug_break(void)
{
#if AINOS_PLATFORM_WIN32
    __debugbreak();
#elif defined(__x86_64__) || defined(__i386__)
    __asm__ volatile("int3");
#elif defined(__aarch64__)
    __asm__ volatile("brk #0");
#else
    raise(SIGTRAP);
#endif
}

#ifdef __cplusplus
}
#endif

#endif /* AINOS_PLATFORM_H */