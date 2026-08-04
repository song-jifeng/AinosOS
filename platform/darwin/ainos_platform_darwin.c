// Ainos OS - Platform Abstraction Layer (macOS Implementation)
// macOS 平台实现: POSIX APIs + macOS 特定调整
//
// Copyright (c) 2024 AinosOS
// SPDX-License-Identifier: MIT

#define AINOS_PLATFORM_IMPLEMENTATION
#include "ainos/platform.h"

#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <pthread.h>
#include <semaphore.h>
#include <sched.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/sysctl.h>
#include <sys/utsname.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/times.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <dirent.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <signal.h>
#include <poll.h>
#include <os/log.h>
#include <dispatch/dispatch.h>
#include <uuid/uuid.h>
#include <TargetConditionals.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach-o/dyld.h>
#include <mach/thread_act.h>
#include <mach/thread_policy.h>

/* ================================================================
 * 内部工具
 * ================================================================ */

static int g_platform_initialized = 0;
static int g_last_error = 0;
static dispatch_once_t g_init_once = 0;

static int errno_to_platform(int sys_errno)
{
    switch (sys_errno) {
        case 0:                     return AINOS_PLATFORM_OK;
        case ENOMEM:                return AINOS_PLATFORM_ERR_NOMEM;
        case EINVAL:                return AINOS_PLATFORM_ERR_INVAL;
        case ETIMEDOUT:             return AINOS_PLATFORM_ERR_TIMEOUT;
        case EBUSY:                 return AINOS_PLATFORM_ERR_BUSY;
        case EAGAIN: case EWOULDBLOCK: return AINOS_PLATFORM_ERR_AGAIN;
        case ENOENT:                return AINOS_PLATFORM_ERR_NOT_FOUND;
        case EACCES: case EPERM:    return AINOS_PLATFORM_ERR_PERM;
        case EEXIST:                return AINOS_PLATFORM_ERR_EXIST;
        case EIO:                   return AINOS_PLATFORM_ERR_IO;
        case EINTR:                 return AINOS_PLATFORM_ERR_INTR;
        case ENOTSUP:               return AINOS_PLATFORM_ERR_NOT_SUP;
        case ECONNREFUSED:          return AINOS_PLATFORM_ERR_CONNREFUSED;
        case ECONNRESET:            return AINOS_PLATFORM_ERR_CONNRESET;
        case EADDRINUSE:            return AINOS_PLATFORM_ERR_ADDRINUSE;
        default:                    return AINOS_PLATFORM_ERR_GENERAL;
    }
}

/* ================================================================
 * 5. 平台初始化和清理
 * ================================================================ */

int ainos_platform_init(void)
{
    __block int ret = AINOS_PLATFORM_OK;
    dispatch_once(&g_init_once, ^{
        g_platform_initialized = 1;
        ret = AINOS_PLATFORM_OK;
    });
    if (!g_platform_initialized) {
        g_platform_initialized = 1;
    }
    return ret;
}

void ainos_platform_cleanup(void)
{
    g_platform_initialized = 0;
    g_init_once = 0;
}

int ainos_platform_is_initialized(void)
{
    return g_platform_initialized;
}

const char* ainos_platform_name(void)
{
    return "darwin";
}

const char* ainos_platform_version(void)
{
    return AINOS_PLATFORM_VERSION;
}

/* ================================================================
 * 6. 互斥锁 (Mutex) API
 * ================================================================ */

int ainos_platform_mutex_init(ainos_platform_mutex_t* mutex, int type)
{
    if (!mutex) return AINOS_PLATFORM_ERR_INVAL;

    pthread_mutex_t* m = malloc(sizeof(pthread_mutex_t));
    if (!m) return AINOS_PLATFORM_ERR_NOMEM;

    pthread_mutexattr_t attr;
    pthread_mutexattr_init(&attr);
    int kind = PTHREAD_MUTEX_NORMAL;
    if (type == AINOS_PLATFORM_MUTEX_RECURSIVE) kind = PTHREAD_MUTEX_RECURSIVE;
    else if (type == AINOS_PLATFORM_MUTEX_ERRORCHECK) kind = PTHREAD_MUTEX_ERRORCHECK;
    pthread_mutexattr_settype(&attr, kind);

    int ret = pthread_mutex_init(m, &attr);
    pthread_mutexattr_destroy(&attr);
    if (ret != 0) { free(m); return errno_to_platform(ret); }

    mutex->_pthread_mutex = m;
    mutex->_is_initialized = 1;
    mutex->_is_recursive = (type == AINOS_PLATFORM_MUTEX_RECURSIVE);
    mutex->_type = type;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mutex_destroy(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_mutex_destroy((pthread_mutex_t*)mutex->_pthread_mutex);
    free(mutex->_pthread_mutex);
    mutex->_pthread_mutex = NULL;
    mutex->_is_initialized = 0;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_mutex_lock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_mutex_lock((pthread_mutex_t*)mutex->_pthread_mutex);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_mutex_trylock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_mutex_trylock((pthread_mutex_t*)mutex->_pthread_mutex);
    if (ret == EBUSY) return AINOS_PLATFORM_ERR_BUSY;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_mutex_unlock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_mutex_unlock((pthread_mutex_t*)mutex->_pthread_mutex);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_mutex_lock_timeout(ainos_platform_mutex_t* mutex, int timeout_ms)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    if (timeout_ms <= 0) return ainos_platform_mutex_trylock(mutex);

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += timeout_ms / 1000;
    ts.tv_nsec += (timeout_ms % 1000) * 1000000L;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }

    int ret = pthread_mutex_timedlock((pthread_mutex_t*)mutex->_pthread_mutex, &ts);
    if (ret == ETIMEDOUT) return AINOS_PLATFORM_ERR_TIMEOUT;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_mutex_is_valid(const ainos_platform_mutex_t* mutex)
{
    return mutex && mutex->_is_initialized;
}

/* ================================================================
 * 7. 读写锁 (RWLock) API
 * ================================================================ */

int ainos_platform_rwlock_init(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock) return AINOS_PLATFORM_ERR_INVAL;
    pthread_rwlock_t* rwl = malloc(sizeof(pthread_rwlock_t));
    if (!rwl) return AINOS_PLATFORM_ERR_NOMEM;
    int ret = pthread_rwlock_init(rwl, NULL);
    if (ret != 0) { free(rwl); return errno_to_platform(ret); }
    rwlock->_pthread_rwlock = rwl;
    rwlock->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_rwlock_destroy(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_rwlock_destroy((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    free(rwlock->_pthread_rwlock);
    rwlock->_pthread_rwlock = NULL;
    rwlock->_is_initialized = 0;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_rwlock_rdlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_rwlock_rdlock((pthread_rwlock_t*)rwlock->_pthread_rwlock) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_rwlock_try_rdlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_rwlock_tryrdlock((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    if (ret == EBUSY) return AINOS_PLATFORM_ERR_BUSY;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_rwlock_wrlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_rwlock_wrlock((pthread_rwlock_t*)rwlock->_pthread_rwlock) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_rwlock_try_wrlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_rwlock_trywrlock((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    if (ret == EBUSY) return AINOS_PLATFORM_ERR_BUSY;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_rwlock_unlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_rwlock_unlock((pthread_rwlock_t*)rwlock->_pthread_rwlock) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

/* ================================================================
 * 8. 条件变量 (Condition Variable) API
 * ================================================================ */

int ainos_platform_cond_init(ainos_platform_cond_t* cond)
{
    if (!cond) return AINOS_PLATFORM_ERR_INVAL;
    pthread_cond_t* c = malloc(sizeof(pthread_cond_t));
    if (!c) return AINOS_PLATFORM_ERR_NOMEM;

    pthread_condattr_t attr;
    pthread_condattr_init(&attr);
    /* macOS 不支持 pthread_condattr_setclock, 使用默认 CLOCK_REALTIME */
    int ret = pthread_cond_init(c, &attr);
    pthread_condattr_destroy(&attr);
    if (ret != 0) { free(c); return errno_to_platform(ret); }
    cond->_pthread_cond = c;
    cond->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_cond_destroy(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_cond_destroy((pthread_cond_t*)cond->_pthread_cond);
    free(cond->_pthread_cond);
    cond->_pthread_cond = NULL;
    cond->_is_initialized = 0;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_cond_wait(ainos_platform_cond_t* cond, ainos_platform_mutex_t* mutex)
{
    if (!cond || !cond->_is_initialized || !mutex) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_cond_wait((pthread_cond_t*)cond->_pthread_cond,
                              (pthread_mutex_t*)mutex->_pthread_mutex) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_cond_timedwait(ainos_platform_cond_t* cond,
                                  ainos_platform_mutex_t* mutex, int timeout_ms)
{
    if (!cond || !cond->_is_initialized || !mutex) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += timeout_ms / 1000;
    ts.tv_nsec += (timeout_ms % 1000) * 1000000L;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    int ret = pthread_cond_timedwait((pthread_cond_t*)cond->_pthread_cond,
                                     (pthread_mutex_t*)mutex->_pthread_mutex, &ts);
    if (ret == ETIMEDOUT) return AINOS_PLATFORM_ERR_TIMEOUT;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_cond_signal(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_cond_signal((pthread_cond_t*)cond->_pthread_cond) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_cond_broadcast(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_cond_broadcast((pthread_cond_t*)cond->_pthread_cond) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

/* ================================================================
 * 9. 信号量 (Semaphore) API
 * ================================================================ */

/* macOS 不支持匿名信号量, 使用 dispatch_semaphore 或命名信号量 */

int ainos_platform_sem_init(ainos_platform_semaphore_t* sem,
                            unsigned int initial_value, unsigned int max_value)
{
    (void)max_value;
    if (!sem) return AINOS_PLATFORM_ERR_INVAL;

    /* macOS 上 sem_init 不可用, 使用 dispatch_semaphore */
    dispatch_semaphore_t ds = dispatch_semaphore_create((long)initial_value);
    if (!ds) return AINOS_PLATFORM_ERR_NOMEM;

    sem->_sem_ptr = (void*)ds;
    sem->_is_initialized = 1;
    sem->_is_named = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_destroy(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    dispatch_release((dispatch_semaphore_t)sem->_sem_ptr);
    sem->_sem_ptr = NULL;
    sem->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_wait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    long ret = dispatch_semaphore_wait((dispatch_semaphore_t)sem->_sem_ptr,
                                       DISPATCH_TIME_FOREVER);
    return (ret == 0) ? AINOS_PLATFORM_OK : AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_sem_trywait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    long ret = dispatch_semaphore_wait((dispatch_semaphore_t)sem->_sem_ptr,
                                       DISPATCH_TIME_NOW);
    return (ret == 0) ? AINOS_PLATFORM_OK : AINOS_PLATFORM_ERR_BUSY;
}

int ainos_platform_sem_timedwait(ainos_platform_semaphore_t* sem, int timeout_ms)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    dispatch_time_t t = dispatch_time(DISPATCH_TIME_NOW,
                                       (int64_t)timeout_ms * NSEC_PER_MSEC);
    long ret = dispatch_semaphore_wait((dispatch_semaphore_t)sem->_sem_ptr, t);
    if (ret != 0) return AINOS_PLATFORM_ERR_TIMEOUT;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_post(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    dispatch_semaphore_signal((dispatch_semaphore_t)sem->_sem_ptr);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_getvalue(ainos_platform_semaphore_t* sem, int* value)
{
    /* dispatch_semaphore 不提供获取当前值的方法 */
    if (!sem || !sem->_is_initialized || !value) return AINOS_PLATFORM_ERR_INVAL;
    *value = 0;
    return AINOS_PLATFORM_ERR_NOT_SUP;
}

/* ================================================================
 * 10. 事件 (Event) API
 * ================================================================ */

int ainos_platform_event_init(ainos_platform_event_t* event,
                              int manual_reset, int initial_state)
{
    if (!event) return AINOS_PLATFORM_ERR_INVAL;
    event->_cond = malloc(sizeof(pthread_cond_t));
    event->_mutex = malloc(sizeof(pthread_mutex_t));
    if (!event->_cond || !event->_mutex) {
        free(event->_cond); free(event->_mutex);
        return AINOS_PLATFORM_ERR_NOMEM;
    }
    pthread_cond_init((pthread_cond_t*)event->_cond, NULL);
    pthread_mutex_init((pthread_mutex_t*)event->_mutex, NULL);
    event->_is_initialized = 1;
    event->_is_manual_reset = manual_reset;
    event->_signaled = initial_state;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_destroy(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_cond_destroy((pthread_cond_t*)event->_cond);
    pthread_mutex_destroy((pthread_mutex_t*)event->_mutex);
    free(event->_cond); free(event->_mutex);
    event->_cond = NULL; event->_mutex = NULL;
    event->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_wait(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock((pthread_mutex_t*)event->_mutex);
    while (!event->_signaled)
        pthread_cond_wait((pthread_cond_t*)event->_cond, (pthread_mutex_t*)event->_mutex);
    if (!event->_is_manual_reset) event->_signaled = 0;
    pthread_mutex_unlock((pthread_mutex_t*)event->_mutex);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_timedwait(ainos_platform_event_t* event, int timeout_ms)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += timeout_ms / 1000;
    ts.tv_nsec += (timeout_ms % 1000) * 1000000L;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    pthread_mutex_lock((pthread_mutex_t*)event->_mutex);
    int ret = AINOS_PLATFORM_OK;
    while (!event->_signaled) {
        int rc = pthread_cond_timedwait((pthread_cond_t*)event->_cond,
                                        (pthread_mutex_t*)event->_mutex, &ts);
        if (rc == ETIMEDOUT) { ret = AINOS_PLATFORM_ERR_TIMEOUT; break; }
    }
    if (!event->_is_manual_reset && event->_signaled) event->_signaled = 0;
    pthread_mutex_unlock((pthread_mutex_t*)event->_mutex);
    return ret;
}

int ainos_platform_event_set(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock((pthread_mutex_t*)event->_mutex);
    event->_signaled = 1;
    if (event->_is_manual_reset) pthread_cond_broadcast((pthread_cond_t*)event->_cond);
    else pthread_cond_signal((pthread_cond_t*)event->_cond);
    pthread_mutex_unlock((pthread_mutex_t*)event->_mutex);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_reset(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock((pthread_mutex_t*)event->_mutex);
    event->_signaled = 0;
    pthread_mutex_unlock((pthread_mutex_t*)event->_mutex);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_pulse(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock((pthread_mutex_t*)event->_mutex);
    event->_signaled = 1;
    pthread_cond_broadcast((pthread_cond_t*)event->_cond);
    if (!event->_is_manual_reset) event->_signaled = 0;
    pthread_mutex_unlock((pthread_mutex_t*)event->_mutex);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 11. 屏障 (Barrier) API
 * ================================================================ */

/* macOS 不支持 pthread_barrier, 使用 dispatch_group 模拟 */

int ainos_platform_barrier_init(ainos_platform_barrier_t* barrier, int count)
{
    if (!barrier || count <= 0) return AINOS_PLATFORM_ERR_INVAL;
    barrier->_count = count;
    barrier->_waiters = 0;
    barrier->_is_initialized = 1;
    barrier->_mutex = malloc(sizeof(pthread_mutex_t));
    barrier->_event = malloc(sizeof(pthread_cond_t));
    if (!barrier->_mutex || !barrier->_event) {
        free(barrier->_mutex); free(barrier->_event);
        return AINOS_PLATFORM_ERR_NOMEM;
    }
    pthread_mutex_init((pthread_mutex_t*)barrier->_mutex, NULL);
    pthread_cond_init((pthread_cond_t*)barrier->_event, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_barrier_destroy(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_destroy((pthread_mutex_t*)barrier->_mutex);
    pthread_cond_destroy((pthread_cond_t*)barrier->_event);
    free(barrier->_mutex); free(barrier->_event);
    barrier->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_barrier_wait(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock((pthread_mutex_t*)barrier->_mutex);
    barrier->_waiters++;
    if (barrier->_waiters >= barrier->_count) {
        barrier->_waiters = 0;
        pthread_cond_broadcast((pthread_cond_t*)barrier->_event);
        pthread_mutex_unlock((pthread_mutex_t*)barrier->_mutex);
        return 1;
    }
    pthread_cond_wait((pthread_cond_t*)barrier->_event,
                      (pthread_mutex_t*)barrier->_mutex);
    pthread_mutex_unlock((pthread_mutex_t*)barrier->_mutex);
    return 0;
}

/* ================================================================
 * 12. 线程池 (Thread Pool) API (stub - macOS 使用 GCD)
 * ================================================================ */

int ainos_platform_threadpool_create(
    ainos_platform_threadpool_t** pool,
    const ainos_platform_threadpool_config_t* config) {
    (void)pool; (void)config;
    return AINOS_PLATFORM_ERR_NOT_SUP;
}

int ainos_platform_threadpool_submit(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_work_func_t func, void* arg) {
    (void)pool; (void)func; (void)arg;
    return AINOS_PLATFORM_ERR_NOT_SUP;
}

int ainos_platform_threadpool_wait(ainos_platform_threadpool_t* pool) {
    (void)pool; return AINOS_PLATFORM_ERR_NOT_SUP;
}

int ainos_platform_threadpool_get_stats(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_stats_t* stats) {
    (void)pool; (void)stats; return AINOS_PLATFORM_ERR_NOT_SUP;
}

int ainos_platform_threadpool_destroy(ainos_platform_threadpool_t* pool) {
    (void)pool; return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 13. 线程 (Thread) API
 * ================================================================ */

typedef struct { ainos_platform_thread_func_t func; void* arg; int exit_code; } thread_wrapper_t;

static void* thread_entry_wrapper(void* arg)
{
    thread_wrapper_t* w = (thread_wrapper_t*)arg;
    w->exit_code = w->func(w->arg);
    return NULL;
}

int ainos_platform_thread_create(ainos_platform_thread_t* thread,
                                 const ainos_platform_thread_attr_t* attr,
                                 ainos_platform_thread_func_t func, void* arg)
{
    if (!thread || !func) return AINOS_PLATFORM_ERR_INVAL;
    thread_wrapper_t* wrapper = malloc(sizeof(thread_wrapper_t));
    if (!wrapper) return AINOS_PLATFORM_ERR_NOMEM;
    wrapper->func = func; wrapper->arg = arg; wrapper->exit_code = 0;

    pthread_attr_t pattr;
    pthread_attr_init(&pattr);
    pthread_attr_setdetachstate(&pattr, PTHREAD_CREATE_JOINABLE);
    if (attr) {
        if (attr->stack_size > 0) pthread_attr_setstacksize(&pattr, attr->stack_size);
        if (attr->is_detached) pthread_attr_setdetachstate(&pattr, PTHREAD_CREATE_DETACHED);
    }
    pthread_t pt;
    int ret = pthread_create(&pt, &pattr, thread_entry_wrapper, wrapper);
    pthread_attr_destroy(&pattr);
    if (ret != 0) { free(wrapper); return errno_to_platform(ret); }

    thread->_pthread = (void*)(uintptr_t)pt;
    thread->_is_valid = 1;
    thread->_tid = 0;

    if (attr && attr->name[0] != '\0') {
        pthread_setname_np(attr->name);
    }
    if (attr && attr->is_detached) { thread->_pthread = NULL; thread->_is_valid = 0; }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_join(ainos_platform_thread_t* thread, int* exit_code)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    void* retval = NULL;
    int ret = pthread_join((pthread_t)(uintptr_t)thread->_pthread, &retval);
    if (ret != 0) return errno_to_platform(ret);
    if (exit_code) *exit_code = (int)(intptr_t)retval;
    thread->_is_valid = 0; thread->_pthread = NULL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_detach(ainos_platform_thread_t* thread)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_detach((pthread_t)(uintptr_t)thread->_pthread);
    if (ret != 0) return errno_to_platform(ret);
    thread->_is_valid = 0; thread->_pthread = NULL;
    return AINOS_PLATFORM_OK;
}

unsigned long long ainos_platform_thread_self_id(void)
{
    return (unsigned long long)pthread_self();
}

int ainos_platform_thread_get_name(char* name, size_t name_size)
{
    if (!name || name_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    pthread_getname_np(pthread_self(), name, name_size);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_set_name(const char* name)
{
    if (!name) return AINOS_PLATFORM_ERR_INVAL;
    pthread_setname_np(name);
    return AINOS_PLATFORM_OK;
}

void ainos_platform_thread_yield(void) { sched_yield(); }

int ainos_platform_thread_sleep(int milliseconds)
{
    if (milliseconds < 0) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts = { milliseconds / 1000, (milliseconds % 1000) * 1000000L };
    int ret;
    do { ret = nanosleep(&ts, &ts); } while (ret != 0 && errno == EINTR);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_thread_is_running(ainos_platform_thread_t* thread)
{
    if (!thread || !thread->_is_valid) return 0;
    int ret = pthread_kill((pthread_t)(uintptr_t)thread->_pthread, 0);
    return (ret == 0) ? 1 : 0;
}

int ainos_platform_thread_get_cpu_time(ainos_platform_thread_t* thread,
                                       uint64_t* user_ns, uint64_t* kernel_ns)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    pthread_t pt = (pthread_t)(uintptr_t)thread->_pthread;
    mach_port_t mt = pthread_mach_thread_np(pt);
    thread_basic_info_data_t info;
    mach_msg_type_number_t count = THREAD_BASIC_INFO_COUNT;
    kern_return_t kr = thread_info(mt, THREAD_BASIC_INFO,
                                   (thread_info_t)&info, &count);
    if (kr != KERN_SUCCESS) return AINOS_PLATFORM_ERR_GENERAL;
    if (user_ns) {
        *user_ns = (uint64_t)info.user_time.seconds * 1000000000ULL +
                   (uint64_t)info.user_time.microseconds * 1000ULL;
    }
    if (kernel_ns) {
        *kernel_ns = (uint64_t)info.system_time.seconds * 1000000000ULL +
                     (uint64_t)info.system_time.microseconds * 1000ULL;
    }
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 13. TLS API
 * ================================================================ */

int ainos_platform_tls_alloc(ainos_platform_tls_t* tls)
{
    if (!tls) return AINOS_PLATFORM_ERR_INVAL;
    pthread_key_t* key = malloc(sizeof(pthread_key_t));
    if (!key) return AINOS_PLATFORM_ERR_NOMEM;
    int ret = pthread_key_create(key, NULL);
    if (ret != 0) { free(key); return errno_to_platform(ret); }
    tls->_pthread_key = key; tls->_is_allocated = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_tls_free(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;
    pthread_key_delete(*(pthread_key_t*)tls->_pthread_key);
    free(tls->_pthread_key); tls->_pthread_key = NULL; tls->_is_allocated = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_tls_set(ainos_platform_tls_t* tls, void* value)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;
    return (pthread_setspecific(*(pthread_key_t*)tls->_pthread_key, value) == 0)
           ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

void* ainos_platform_tls_get(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return NULL;
    return pthread_getspecific(*(pthread_key_t*)tls->_pthread_key);
}

/* ================================================================
 * 14. Socket API
 * ================================================================ */

int ainos_platform_socket_create(ainos_platform_socket_t* sock, int domain, int type, int protocol)
{
    if (!sock) return AINOS_PLATFORM_ERR_INVAL;
    int ud = AF_INET, ut = SOCK_STREAM, up = 0;
    if (domain == AINOS_PLATFORM_AF_INET) ud = AF_INET;
    else if (domain == AINOS_PLATFORM_AF_INET6) ud = AF_INET6;
    else if (domain == AINOS_PLATFORM_AF_UNIX) ud = AF_UNIX;
    if (type == AINOS_PLATFORM_SOCK_STREAM) ut = SOCK_STREAM;
    else if (type == AINOS_PLATFORM_SOCK_DGRAM) ut = SOCK_DGRAM;
    if (protocol == AINOS_PLATFORM_IPPROTO_TCP) up = IPPROTO_TCP;
    else if (protocol == AINOS_PLATFORM_IPPROTO_UDP) up = IPPROTO_UDP;
    int fd = socket(ud, ut, up);
    if (fd < 0) return errno_to_platform(errno);
    sock->_fd = fd; sock->_domain = domain; sock->_type = type;
    sock->_protocol = protocol; sock->_is_valid = 1; sock->_is_nonblocking = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_close(ainos_platform_socket_t* sock)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (close(sock->_fd) < 0) return errno_to_platform(errno);
    sock->_is_valid = 0; sock->_fd = -1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_shutdown(ainos_platform_socket_t* sock, int how)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int uh = SHUT_RDWR;
    if (how == AINOS_PLATFORM_SHUT_RD) uh = SHUT_RD;
    else if (how == AINOS_PLATFORM_SHUT_WR) uh = SHUT_WR;
    if (shutdown(sock->_fd, uh) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_bind(ainos_platform_socket_t* sock, const ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;
    if (bind(sock->_fd, (const struct sockaddr*)addr->_data, addr->_len) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_listen(ainos_platform_socket_t* sock, int backlog)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (listen(sock->_fd, backlog) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_accept(ainos_platform_socket_t* sock, ainos_platform_socket_t* client_sock, ainos_platform_sockaddr_t* client_addr)
{
    if (!sock || !sock->_is_valid || !client_sock) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_storage addr; socklen_t addr_len = sizeof(addr);
    int fd = accept(sock->_fd, (struct sockaddr*)&addr, &addr_len);
    if (fd < 0) return errno_to_platform(errno);
    client_sock->_fd = fd; client_sock->_domain = sock->_domain;
    client_sock->_type = sock->_type; client_sock->_protocol = sock->_protocol;
    client_sock->_is_valid = 1; client_sock->_is_nonblocking = 0;
    if (client_addr) { memcpy(client_addr->_data, &addr, addr_len); client_addr->_len = addr_len; }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_connect(ainos_platform_socket_t* sock, const ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;
    if (connect(sock->_fd, (const struct sockaddr*)addr->_data, addr->_len) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_send(ainos_platform_socket_t* sock, const void* data, int len, int flags)
{
    if (!sock || !sock->_is_valid || !data || len < 0) return AINOS_PLATFORM_ERR_INVAL;
    ssize_t ret = send(sock->_fd, data, (size_t)len, flags);
    if (ret < 0) return -errno_to_platform(errno);
    return (int)ret;
}

int ainos_platform_socket_recv(ainos_platform_socket_t* sock, void* buf, int len, int flags)
{
    if (!sock || !sock->_is_valid || !buf || len < 0) return AINOS_PLATFORM_ERR_INVAL;
    ssize_t ret = recv(sock->_fd, buf, (size_t)len, flags);
    if (ret < 0) return -errno_to_platform(errno);
    return (int)ret;
}

int ainos_platform_socket_set_nonblocking(ainos_platform_socket_t* sock, int nonblocking)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int flags = fcntl(sock->_fd, F_GETFL, 0);
    if (flags < 0) return errno_to_platform(errno);
    if (nonblocking) flags |= O_NONBLOCK; else flags &= ~O_NONBLOCK;
    if (fcntl(sock->_fd, F_SETFL, flags) < 0) return errno_to_platform(errno);
    sock->_is_nonblocking = nonblocking;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_poll(ainos_platform_pollfd_t* fds, int nfds, int timeout_ms)
{
    if (!fds || nfds <= 0) return AINOS_PLATFORM_ERR_INVAL;
    struct pollfd* pfd = malloc(sizeof(struct pollfd) * nfds);
    if (!pfd) return AINOS_PLATFORM_ERR_NOMEM;
    for (int i = 0; i < nfds; i++) {
        pfd[i].fd = fds[i].sock ? fds[i].sock->_fd : -1; pfd[i].events = 0; pfd[i].revents = 0;
        if (fds[i].events & AINOS_PLATFORM_SOCKET_POLLIN) pfd[i].events |= POLLIN;
        if (fds[i].events & AINOS_PLATFORM_SOCKET_POLLOUT) pfd[i].events |= POLLOUT;
    }
    int ret = poll(pfd, nfds, timeout_ms);
    if (ret < 0) { free(pfd); return -errno_to_platform(errno); }
    for (int i = 0; i < nfds; i++) {
        fds[i].revents = 0;
        if (pfd[i].revents & POLLIN) fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLIN;
        if (pfd[i].revents & POLLOUT) fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLOUT;
        if (pfd[i].revents & POLLERR) fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLERR;
    }
    free(pfd); return ret;
}

/* ================================================================
 * 15. Socket 地址构造 API
 * ================================================================ */

int ainos_platform_sockaddr_set_inet4(ainos_platform_sockaddr_t* addr, const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in* sin = (struct sockaddr_in*)addr->_data;
    memset(sin, 0, sizeof(*sin));
    sin->sin_family = AF_INET; sin->sin_port = htons(port);
    if (ip) inet_pton(AF_INET, ip, &sin->sin_addr); else sin->sin_addr.s_addr = INADDR_ANY;
    addr->_len = sizeof(*sin);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_set_inet6(ainos_platform_sockaddr_t* addr, const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in6* sin6 = (struct sockaddr_in6*)addr->_data;
    memset(sin6, 0, sizeof(*sin6));
    sin6->sin6_family = AF_INET6; sin6->sin6_port = htons(port);
    if (ip) inet_pton(AF_INET6, ip, &sin6->sin6_addr); else sin6->sin6_addr = in6addr_any;
    addr->_len = sizeof(*sin6);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_set_unix(ainos_platform_sockaddr_t* addr, const char* path)
{
    if (!addr || !path) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_un* sun = (struct sockaddr_un*)addr->_data;
    memset(sun, 0, sizeof(*sun)); sun->sun_family = AF_UNIX;
    strncpy(sun->sun_path, path, sizeof(sun->sun_path) - 1);
    addr->_len = sizeof(*sun);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dns_resolve(const char* hostname, ainos_platform_sockaddr_t* addrs, int* addr_count)
{
    if (!hostname || !addrs || !addr_count || *addr_count <= 0) return AINOS_PLATFORM_ERR_INVAL;
    struct addrinfo hints, *result = NULL;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC; hints.ai_socktype = SOCK_STREAM;
    int ret = getaddrinfo(hostname, NULL, &hints, &result);
    if (ret != 0) return AINOS_PLATFORM_ERR_NOT_FOUND;
    int count = 0;
    for (struct addrinfo* rp = result; rp && count < *addr_count; rp = rp->ai_next) {
        memcpy(addrs[count]._data, rp->ai_addr, rp->ai_addrlen);
        addrs[count]._len = rp->ai_addrlen; count++;
    }
    freeaddrinfo(result); *addr_count = count;
    return count > 0 ? AINOS_PLATFORM_OK : AINOS_PLATFORM_ERR_NOT_FOUND;
}

/* ================================================================
 * 16. 文件 I/O API
 * ================================================================ */

static int file_flags_to_unix(int flags)
{
    int f = 0;
    if (flags & AINOS_PLATFORM_FILE_O_RDWR) f = O_RDWR;
    else if (flags & AINOS_PLATFORM_FILE_O_WRONLY) f = O_WRONLY;
    else f = O_RDONLY;
    if (flags & AINOS_PLATFORM_FILE_O_CREAT) f |= O_CREAT;
    if (flags & AINOS_PLATFORM_FILE_O_TRUNC) f |= O_TRUNC;
    if (flags & AINOS_PLATFORM_FILE_O_APPEND) f |= O_APPEND;
    if (flags & AINOS_PLATFORM_FILE_O_EXCL) f |= O_EXCL;
    if (flags & AINOS_PLATFORM_FILE_O_SYNC) f |= O_SYNC;
    return f;
}

int ainos_platform_file_open(ainos_platform_file_t* file, const char* path, int flags, int mode)
{
    if (!file || !path) return AINOS_PLATFORM_ERR_INVAL;
    if (mode == 0) mode = 0644;
    int fd = open(path, file_flags_to_unix(flags), mode);
    if (fd < 0) return errno_to_platform(errno);
    file->_fd = fd; file->_is_valid = 1; file->_access_mode = flags;
    strncpy(file->_path, path, sizeof(file->_path) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_close(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (close(file->_fd) < 0) return errno_to_platform(errno);
    file->_is_valid = 0; file->_fd = -1;
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_file_read(ainos_platform_file_t* file, void* buf, int64_t count)
{
    if (!file || !file->_is_valid || !buf || count < 0) return AINOS_PLATFORM_ERR_INVAL;
    ssize_t ret = read(file->_fd, buf, (size_t)count);
    if (ret < 0) return -errno_to_platform(errno);
    return (int64_t)ret;
}

int64_t ainos_platform_file_write(ainos_platform_file_t* file, const void* buf, int64_t count)
{
    if (!file || !file->_is_valid || !buf || count < 0) return AINOS_PLATFORM_ERR_INVAL;
    ssize_t ret = write(file->_fd, buf, (size_t)count);
    if (ret < 0) return -errno_to_platform(errno);
    return (int64_t)ret;
}

int ainos_platform_file_seek(ainos_platform_file_t* file, int64_t offset, int whence)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int w = SEEK_SET;
    if (whence == AINOS_PLATFORM_FILE_SEEK_CUR) w = SEEK_CUR;
    else if (whence == AINOS_PLATFORM_FILE_SEEK_END) w = SEEK_END;
    if (lseek(file->_fd, offset, w) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_file_tell(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    off_t ret = lseek(file->_fd, 0, SEEK_CUR);
    return (ret < 0) ? -errno_to_platform(errno) : (int64_t)ret;
}

int ainos_platform_file_stat(const char* path, ainos_platform_file_stat_t* stat)
{
    if (!path || !stat) return AINOS_PLATFORM_ERR_INVAL;
    struct stat st;
    if (stat(path, &st) < 0) return errno_to_platform(errno);
    memset(stat, 0, sizeof(*stat));
    stat->size = (uint64_t)st.st_size;
    stat->is_directory = S_ISDIR(st.st_mode);
    stat->is_regular = S_ISREG(st.st_mode);
    stat->is_symlink = S_ISLNK(st.st_mode);
    stat->permissions = st.st_mode & 0777;
    stat->created_time = (uint64_t)st.st_ctime * 1000;
    stat->modified_time = (uint64_t)st.st_mtime * 1000;
    stat->accessed_time = (uint64_t)st.st_atime * 1000;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_unlink(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    if (unlink(path) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_rename(const char* old_path, const char* new_path)
{
    if (!old_path || !new_path) return AINOS_PLATFORM_ERR_INVAL;
    if (rename(old_path, new_path) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_exists(const char* path)
{
    return path ? (access(path, F_OK) == 0) : 0;
}

/* ================================================================
 * 17. 目录操作 API
 * ================================================================ */

int ainos_platform_dir_open(ainos_platform_dir_t* dir, const char* path)
{
    if (!dir || !path) return AINOS_PLATFORM_ERR_INVAL;
    DIR* d = opendir(path);
    if (!d) return errno_to_platform(errno);
    dir->_handle = d; dir->_is_valid = 1; dir->_entry_index = 0;
    strncpy(dir->_path, path, sizeof(dir->_path) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_read(ainos_platform_dir_t* dir, ainos_platform_dirent_t* entry)
{
    if (!dir || !dir->_is_valid || !entry) return AINOS_PLATFORM_ERR_INVAL;
    struct dirent* de = readdir((DIR*)dir->_handle);
    if (!de) return 0;
    strncpy(entry->name, de->d_name, sizeof(entry->name) - 1);
    entry->name[sizeof(entry->name) - 1] = '\0';
    entry->is_directory = (de->d_type == DT_DIR);
    entry->is_regular = (de->d_type == DT_REG);
    entry->size = 0;
    return 1;
}

int ainos_platform_dir_close(ainos_platform_dir_t* dir)
{
    if (!dir || !dir->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (closedir((DIR*)dir->_handle) < 0) return errno_to_platform(errno);
    dir->_is_valid = 0; dir->_handle = NULL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_mkdir(const char* path, int mode)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    if (mode == 0) mode = 0755;
    if (mkdir(path, (mode_t)mode) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_rmdir(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    if (rmdir(path) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_getcwd(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (!getcwd(buf, buf_size)) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 18. 内存管理 API
 * ================================================================ */

void* ainos_platform_mem_alloc(size_t size) { return (size == 0) ? NULL : malloc(size); }
void* ainos_platform_mem_calloc(size_t num, size_t size) { return calloc(1, num * size); }
void* ainos_platform_mem_realloc(void* ptr, size_t new_size) {
    if (new_size == 0) { free(ptr); return NULL; } return realloc(ptr, new_size);
}
void ainos_platform_mem_free(void* ptr) { free(ptr); }

void* ainos_platform_mem_aligned_alloc(size_t alignment, size_t size) {
    void* ptr = NULL;
    if (posix_memalign(&ptr, alignment, size) != 0) return NULL;
    return ptr;
}
void ainos_platform_mem_aligned_free(void* ptr) { free(ptr); }

int ainos_platform_mem_get_page_size(void) {
    long ret = sysconf(_SC_PAGESIZE);
    return (ret > 0) ? (int)ret : 4096;
}

int64_t ainos_platform_mem_get_available_memory(void) {
    mach_port_t host = mach_host_self();
    vm_statistics64_data_t vm_stat;
    mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
    if (host_statistics64(host, HOST_VM_INFO64, (host_info64_t)&vm_stat, &count) != KERN_SUCCESS)
        return -1;
    int64_t page_size = ainos_platform_mem_get_page_size();
    return (int64_t)(vm_stat.free_count + vm_stat.inactive_count) * page_size;
}

int64_t ainos_platform_mem_get_total_physical_memory(void) {
    int64_t mem = 0;
    size_t len = sizeof(mem);
    if (sysctlbyname("hw.memsize", &mem, &len, NULL, 0) == 0)
        return mem;
    return -1;
}

int64_t ainos_platform_mem_get_process_memory(void) {
    struct task_basic_info info;
    mach_msg_type_number_t count = TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_BASIC_INFO, (task_info_t)&info, &count) == KERN_SUCCESS)
        return (int64_t)info.resident_size;
    return -1;
}

/* ================================================================
 * 19. 原子操作 API
 * ================================================================ */

void ainos_platform_atomic32_init(ainos_platform_atomic32_t* a, int32_t v) { if (a) __sync_lock_test_and_set(&a->_value, v); }
void ainos_platform_atomic64_init(ainos_platform_atomic64_t* a, int64_t v) { if (a) __sync_lock_test_and_set(&a->_value, v); }
int32_t ainos_platform_atomic32_load(ainos_platform_atomic32_t* a) { return a ? __sync_fetch_and_add(&a->_value, 0) : 0; }
int64_t ainos_platform_atomic64_load(ainos_platform_atomic64_t* a) { return a ? __sync_fetch_and_add(&a->_value, 0) : 0; }
void ainos_platform_atomic32_store(ainos_platform_atomic32_t* a, int32_t v) { if (a) __sync_lock_test_and_set(&a->_value, v); }
void ainos_platform_atomic64_store(ainos_platform_atomic64_t* a, int64_t v) { if (a) __sync_lock_test_and_set(&a->_value, v); }
int32_t ainos_platform_atomic32_exchange(ainos_platform_atomic32_t* a, int32_t v) { return a ? __sync_lock_test_and_set(&a->_value, v) : 0; }
int64_t ainos_platform_atomic64_exchange(ainos_platform_atomic64_t* a, int64_t v) { return a ? __sync_lock_test_and_set(&a->_value, v) : 0; }
int32_t ainos_platform_atomic32_compare_exchange(ainos_platform_atomic32_t* a, int32_t e, int32_t d) {
    return a ? __sync_val_compare_and_swap(&a->_value, e, d) : 0;
}
int64_t ainos_platform_atomic64_compare_exchange(ainos_platform_atomic64_t* a, int64_t e, int64_t d) {
    return a ? __sync_val_compare_and_swap(&a->_value, e, d) : 0;
}
int32_t ainos_platform_atomic32_fetch_add(ainos_platform_atomic32_t* a, int32_t v) { return a ? __sync_fetch_and_add(&a->_value, v) : 0; }
int64_t ainos_platform_atomic64_fetch_add(ainos_platform_atomic64_t* a, int64_t v) { return a ? __sync_fetch_and_add(&a->_value, v) : 0; }
int32_t ainos_platform_atomic32_fetch_sub(ainos_platform_atomic32_t* a, int32_t v) { return a ? __sync_fetch_and_sub(&a->_value, v) : 0; }
int64_t ainos_platform_atomic64_fetch_sub(ainos_platform_atomic64_t* a, int64_t v) { return a ? __sync_fetch_and_sub(&a->_value, v) : 0; }

/* ================================================================
 * 20. 时间 API
 * ================================================================ */

int ainos_platform_time_now(ainos_platform_time_t* t) {
    if (!t) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    t->seconds = (int64_t)ts.tv_sec; t->nanoseconds = (int64_t)ts.tv_nsec;
    t->raw_counter = (int64_t)mach_absolute_time();
    mach_timebase_info_data_t info;
    mach_timebase_info(&info);
    t->raw_frequency = (int64_t)(NSEC_PER_SEC * info.denom / info.numer);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_now_ms(void) {
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000LL + (int64_t)ts.tv_nsec / 1000000;
}

int64_t ainos_platform_time_monotonic_ns(void) {
    return (int64_t)mach_continuous_time();
}

int ainos_platform_time_sleep_ms(int ms) {
    if (ms < 0) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };
    int ret; do { ret = nanosleep(&ts, &ts); } while (ret != 0 && errno == EINTR);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int64_t ainos_platform_time_get_tick_count(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (int64_t)ts.tv_sec * 1000LL + (int64_t)ts.tv_nsec / 1000000;
}

int ainos_platform_time_format(const ainos_platform_time_t* t, const char* fmt, char* buf, size_t buf_size) {
    if (!t || !fmt || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    time_t sec = (time_t)t->seconds; struct tm* tm_info = localtime(&sec);
    if (!tm_info) { buf[0] = '\0'; return AINOS_PLATFORM_ERR_GENERAL; }
    if (strftime(buf, buf_size, fmt, tm_info) == 0) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_diff_ns(const ainos_platform_time_t* t1, const ainos_platform_time_t* t2) {
    if (!t1 || !t2) return 0;
    return (t1->seconds - t2->seconds) * 1000000000LL + (t1->nanoseconds - t2->nanoseconds);
}

/* ================================================================
 * 21. 进程管理 API
 * ================================================================ */

int ainos_platform_process_spawn(ainos_platform_process_t* process, const char* path, char* const argv[], int flags) {
    if (!process || !path) return AINOS_PLATFORM_ERR_INVAL;
    pid_t pid = fork();
    if (pid < 0) return errno_to_platform(errno);
    if (pid == 0) {
        if (flags & AINOS_PLATFORM_PROCESS_NEW_PGROUP) setpgid(0, 0);
        if (flags & AINOS_PLATFORM_PROCESS_SEARCH_PATH) execvp(path, argv);
        else execv(path, argv);
        _exit(127);
    }
    process->_pid = pid; process->_is_valid = 1; process->_exit_code = 0;
    process->_has_exited = 0;
    if (flags & AINOS_PLATFORM_PROCESS_DETACHED) signal(SIGCHLD, SIG_IGN);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_wait(ainos_platform_process_t* process, int* exit_code) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int status; pid_t ret = waitpid(process->_pid, &status, 0);
    if (ret < 0) return errno_to_platform(errno);
    process->_has_exited = 1;
    if (WIFEXITED(status)) process->_exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status)) process->_exit_code = -WTERMSIG(status);
    if (exit_code) *exit_code = process->_exit_code;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_pid(void) { return (int)getpid(); }

int ainos_platform_process_get_name(char* name, size_t name_size) {
    if (!name || name_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    const char* base = getprogname();
    strncpy(name, base ? base : "unknown", name_size - 1);
    name[name_size - 1] = '\0';
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_path(char* path, size_t path_size) {
    uint32_t len = (uint32_t)path_size;
    if (_NSGetExecutablePath(path, &len) != 0) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 22. 动态库加载 API
 * ================================================================ */

int ainos_platform_dlopen(ainos_platform_library_t* lib, const char* path) {
    if (!lib || !path) return AINOS_PLATFORM_ERR_INVAL;
    void* handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!handle) return AINOS_PLATFORM_ERR_NOT_FOUND;
    lib->_handle = handle; lib->_is_valid = 1;
    strncpy(lib->_path, path, sizeof(lib->_path) - 1);
    return AINOS_PLATFORM_OK;
}

void* ainos_platform_dlsym(ainos_platform_library_t* lib, const char* symbol) {
    return (lib && lib->_is_valid && symbol) ? dlsym(lib->_handle, symbol) : NULL;
}

int ainos_platform_dlclose(ainos_platform_library_t* lib) {
    if (!lib || !lib->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (dlclose(lib->_handle) != 0) return AINOS_PLATFORM_ERR_GENERAL;
    lib->_is_valid = 0; lib->_handle = NULL; return AINOS_PLATFORM_OK;
}

const char* ainos_platform_dlerror(void) { return dlerror(); }

/* ================================================================
 * 23. 环境变量 API
 * ================================================================ */

const char* ainos_platform_getenv(const char* name) { return name ? getenv(name) : NULL; }

int ainos_platform_setenv(const char* name, const char* value, int overwrite) {
    if (!name || !value) return AINOS_PLATFORM_ERR_INVAL;
    if (setenv(name, value, overwrite) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_unsetenv(const char* name) {
    if (!name) return AINOS_PLATFORM_ERR_INVAL;
    if (unsetenv(name) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 24. 错误处理 API
 * ================================================================ */

int ainos_platform_get_last_error(void) { return g_last_error; }
int ainos_platform_errno_to_platform(int sys_errno) { return errno_to_platform(sys_errno); }

const char* ainos_platform_strerror(int err) {
    switch (err) {
        case AINOS_PLATFORM_OK: return "Success";
        case AINOS_PLATFORM_ERR_GENERAL: return "General error";
        case AINOS_PLATFORM_ERR_NOMEM: return "Out of memory";
        case AINOS_PLATFORM_ERR_INVAL: return "Invalid argument";
        case AINOS_PLATFORM_ERR_TIMEOUT: return "Operation timed out";
        case AINOS_PLATFORM_ERR_BUSY: return "Resource busy";
        case AINOS_PLATFORM_ERR_AGAIN: return "Try again";
        case AINOS_PLATFORM_ERR_NOT_FOUND: return "Not found";
        case AINOS_PLATFORM_ERR_PERM: return "Permission denied";
        case AINOS_PLATFORM_ERR_EXIST: return "Already exists";
        case AINOS_PLATFORM_ERR_IO: return "I/O error";
        case AINOS_PLATFORM_ERR_INTR: return "Interrupted";
        case AINOS_PLATFORM_ERR_NOT_SUP: return "Not supported";
        case AINOS_PLATFORM_ERR_CONNREFUSED: return "Connection refused";
        case AINOS_PLATFORM_ERR_CONNRESET: return "Connection reset";
        case AINOS_PLATFORM_ERR_ADDRINUSE: return "Address in use";
        case AINOS_PLATFORM_ERR_WOULDBLOCK: return "Operation would block";
        default: return "Unknown error";
    }
}

void ainos_platform_set_last_error(int err) { g_last_error = err; }

/* ================================================================
 * 25. 系统信息 API
 * ================================================================ */

int ainos_platform_sys_get_cpu_info(ainos_platform_cpu_info_t* info) {
    if (!info) return AINOS_PLATFORM_ERR_INVAL;
    memset(info, 0, sizeof(*info));
    int ncpu = 0; size_t len = sizeof(ncpu);
    sysctlbyname("hw.logicalcpu", &ncpu, &len, NULL, 0);
    info->logical_cores = ncpu;
    sysctlbyname("hw.physicalcpu", &ncpu, &len, NULL, 0);
    info->physical_cores = ncpu;
    int64_t freq = 0; len = sizeof(freq);
    sysctlbyname("hw.cpufrequency", &freq, &len, NULL, 0);
    info->max_freq_mhz = (double)freq / 1000000.0;
    info->is_64bit = (sizeof(void*) == 8);
    info->cache_line_size = 64;
    char cpu_brand[256] = {0}; len = sizeof(cpu_brand);
    sysctlbyname("machdep.cpu.brand_string", &cpu_brand, &len, NULL, 0);
    strncpy(info->name, cpu_brand, sizeof(info->name) - 1);
    info->l1d_cache = 64; info->l1i_cache = 64; info->l2_cache = 256; info->l3_cache = 8192;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_hostname(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    return (gethostname(buf, buf_size) == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_sys_get_os_info(char* os_name, size_t name_size, char* os_version, size_t ver_size) {
    char os[256] = {0}; size_t len = sizeof(os);
    sysctlbyname("kern.ostype", os, &len, NULL, 0);
    if (os_name) snprintf(os_name, name_size, "%s", os);
    len = sizeof(os);
    sysctlbyname("kern.osrelease", os, &len, NULL, 0);
    if (os_version) snprintf(os_version, ver_size, "macOS %s", os);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_sys_get_uptime(void) {
    struct timeval boottime; size_t len = sizeof(boottime);
    if (sysctlbyname("kern.boottime", &boottime, &len, NULL, 0) == 0) {
        struct timeval now; gettimeofday(&now, NULL);
        return (int64_t)(now.tv_sec - boottime.tv_sec);
    }
    return -1;
}

/* ================================================================
 * 26. UUID 生成 API
 * ================================================================ */

int ainos_platform_uuid_v4_generate(char* buf, size_t buf_size) {
    if (!buf || buf_size < 37) return AINOS_PLATFORM_ERR_INVAL;
    uuid_t uuid; uuid_generate_random(uuid);
    uuid_unparse_lower(uuid, buf);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 27. 日志 API
 * ================================================================ */

static ainos_platform_log_func_t g_log_callback = NULL;
static void* g_log_user_data = NULL;
static int g_log_level = AINOS_PLATFORM_LOG_INFO;

void ainos_platform_log_set_callback(ainos_platform_log_func_t callback, void* user_data) {
    g_log_callback = callback; g_log_user_data = user_data;
}

void ainos_platform_log_set_level(int level) { g_log_level = level; }

void ainos_platform_log_write(int level, const char* file, int line, const char* func, const char* fmt, ...) {
    if (level < g_log_level) return;
    char msg[4096]; va_list args;
    va_start(args, fmt); vsnprintf(msg, sizeof(msg), fmt, args); va_end(args);
    if (g_log_callback) {
        char formatted[8192];
        snprintf(formatted, sizeof(formatted), "%s:%d (%s) %s", file, line, func, msg);
        g_log_callback(level, formatted, g_log_user_data);
    } else {
        /* macOS: 使用 os_log */
        os_log_t log = os_log_create("com.ainos.platform", "default");
        os_log_with_type(log, OS_LOG_TYPE_DEFAULT, "%{public}s", msg);
        fflush(stderr);
    }
}