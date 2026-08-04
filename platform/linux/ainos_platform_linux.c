// Ainos OS - Platform Abstraction Layer (Linux Implementation)
// Linux Âπ≥Âè∞ÂÆûÁé∞: POSIX APIs
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
#include <sys/sysinfo.h>
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
#include <syslog.h>
#include <link.h>
#include <uuid/uuid.h>
#include <cpuid.h>
#include <sys/syscall.h>
#include <sys/prctl.h>

/* ================================================================
 * ÂÜÖÈÉ®Â∑•ÂÖ∑
 * ================================================================ */

static int g_platform_initialized = 0;
static int g_last_error = 0;

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
 * 5. Âπ≥Âè∞ÂàùÂßãÂåñÂíåÊ∏ÖÁêÜ
 * ================================================================ */

int ainos_platform_init(void)
{
    if (g_platform_initialized) return AINOS_PLATFORM_OK;
    g_platform_initialized = 1;
    return AINOS_PLATFORM_OK;
}

void ainos_platform_cleanup(void)
{
    g_platform_initialized = 0;
}

int ainos_platform_is_initialized(void)
{
    return g_platform_initialized;
}

const char* ainos_platform_name(void)
{
    return "linux";
}

const char* ainos_platform_version(void)
{
    return AINOS_PLATFORM_VERSION;
}

/* ================================================================
 * 6. ‰∫íÊñ•ÈîÅ (Mutex) API
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
 * 7. ËØªÂÜôÈîÅ (RWLock) API
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
    int ret = pthread_rwlock_rdlock((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
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
    int ret = pthread_rwlock_wrlock((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
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
    int ret = pthread_rwlock_unlock((pthread_rwlock_t*)rwlock->_pthread_rwlock);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

/* ================================================================
 * 8. Êù°‰ª∂ÂèòÈáè (Condition Variable) API
 * ================================================================ */

int ainos_platform_cond_init(ainos_platform_cond_t* cond)
{
    if (!cond) return AINOS_PLATFORM_ERR_INVAL;
    pthread_cond_t* c = malloc(sizeof(pthread_cond_t));
    if (!c) return AINOS_PLATFORM_ERR_NOMEM;
    int ret = pthread_cond_init(c, NULL);
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
    int ret = pthread_cond_wait((pthread_cond_t*)cond->_pthread_cond,
                                (pthread_mutex_t*)mutex->_pthread_mutex);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
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
    int ret = pthread_cond_signal((pthread_cond_t*)cond->_pthread_cond);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_cond_broadcast(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_cond_broadcast((pthread_cond_t*)cond->_pthread_cond);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

/* ================================================================
 * 9. ‰ø°Âè∑Èáè (Semaphore) API
 * ================================================================ */

int ainos_platform_sem_init(ainos_platform_semaphore_t* sem,
                            unsigned int initial_value, unsigned int max_value)
{
    (void)max_value;
    if (!sem) return AINOS_PLATFORM_ERR_INVAL;
    sem_t* s = malloc(sizeof(sem_t));
    if (!s) return AINOS_PLATFORM_ERR_NOMEM;
    if (sem_init(s, 0, initial_value) != 0) { free(s); return errno_to_platform(errno); }
    sem->_sem_ptr = s;
    sem->_is_initialized = 1;
    sem->_is_named = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_destroy(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    sem_destroy((sem_t*)sem->_sem_ptr);
    free(sem->_sem_ptr);
    sem->_sem_ptr = NULL;
    sem->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_wait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = sem_wait((sem_t*)sem->_sem_ptr);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_sem_trywait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = sem_trywait((sem_t*)sem->_sem_ptr);
    if (ret != 0) return (errno == EAGAIN) ? AINOS_PLATFORM_ERR_BUSY : errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_timedwait(ainos_platform_semaphore_t* sem, int timeout_ms)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_sec += timeout_ms / 1000;
    ts.tv_nsec += (timeout_ms % 1000) * 1000000L;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    int ret = sem_timedwait((sem_t*)sem->_sem_ptr, &ts);
    if (ret != 0) return (errno == ETIMEDOUT) ? AINOS_PLATFORM_ERR_TIMEOUT : errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_post(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = sem_post((sem_t*)sem->_sem_ptr);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_sem_getvalue(ainos_platform_semaphore_t* sem, int* value)
{
    if (!sem || !sem->_is_initialized || !value) return AINOS_PLATFORM_ERR_INVAL;
    int ret = sem_getvalue((sem_t*)sem->_sem_ptr, value);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}


/* ================================================================
 * 10. ÔøΩ¬ºÔøΩ (Event) API
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
 * 11. ÔøΩÔøΩÔøΩÔøΩ (Barrier) API
 * ================================================================ */

int ainos_platform_barrier_init(ainos_platform_barrier_t* barrier, int count)
{
    if (!barrier || count <= 0) return AINOS_PLATFORM_ERR_INVAL;
    pthread_barrier_t* b = malloc(sizeof(pthread_barrier_t));
    if (!b) return AINOS_PLATFORM_ERR_NOMEM;
    int ret = pthread_barrier_init(b, NULL, (unsigned int)count);
    if (ret != 0) { free(b); return errno_to_platform(ret); }
    barrier->_pthread_barrier = b;
    barrier->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_barrier_destroy(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_barrier_destroy((pthread_barrier_t*)barrier->_pthread_barrier);
    free(barrier->_pthread_barrier);
    barrier->_pthread_barrier = NULL;
    barrier->_is_initialized = 0;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_barrier_wait(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_barrier_wait((pthread_barrier_t*)barrier->_pthread_barrier);
    if (ret == PTHREAD_BARRIER_SERIAL_THREAD) return 1;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}


/* ================================================================
 * 12. ÔøΩﬂ≥ÔøΩ (Thread) API
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
    thread->_tid = (pid_t)syscall(SYS_gettid);

    if (attr && attr->name[0] != ' ') ainos_platform_thread_set_name(attr->name);
    if (attr && attr->priority != AINOS_PLATFORM_THREAD_PRIO_NORMAL) {
        struct sched_param sp;
        int policy = SCHED_OTHER;
        int minp = sched_get_priority_min(policy), maxp = sched_get_priority_max(policy);
        sp.sched_priority = minp + (maxp - minp) * attr->priority / 5;
        pthread_setschedparam(pt, policy, &sp);
    }
    if (attr && attr->affinity >= 0) {
        cpu_set_t cpuset; CPU_ZERO(&cpuset); CPU_SET(attr->affinity, &cpuset);
        pthread_setaffinity_np(pt, sizeof(cpu_set_t), &cpuset);
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
    prctl(PR_GET_NAME, name, 0, 0, 0);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_set_name(const char* name)
{
    if (!name) return AINOS_PLATFORM_ERR_INVAL;
    prctl(PR_SET_NAME, name, 0, 0, 0);
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
    clockid_t cid;
    int ret = pthread_getcpuclockid((pthread_t)(uintptr_t)thread->_pthread, &cid);
    if (ret != 0) return errno_to_platform(ret);
    struct timespec ts;
    ret = clock_gettime(cid, &ts);
    if (ret != 0) return errno_to_platform(errno);
    if (user_ns) *user_ns = (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
    if (kernel_ns) *kernel_ns = 0;
    return AINOS_PLATFORM_OK;
}


/* ================================================================
 * 13. ÔøΩﬂ≥Ã±ÔøΩÔøΩÿ¥Ê¥¢ (TLS) API
 * ================================================================ */

int ainos_platform_tls_alloc(ainos_platform_tls_t* tls)
{
    if (!tls) return AINOS_PLATFORM_ERR_INVAL;
    pthread_key_t* key = malloc(sizeof(pthread_key_t));
    if (!key) return AINOS_PLATFORM_ERR_NOMEM;
    int ret = pthread_key_create(key, NULL);
    if (ret != 0) { free(key); return errno_to_platform(ret); }
    tls->_pthread_key = key;
    tls->_is_allocated = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_tls_free(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_key_delete(*(pthread_key_t*)tls->_pthread_key);
    free(tls->_pthread_key);
    tls->_pthread_key = NULL;
    tls->_is_allocated = 0;
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

int ainos_platform_tls_set(ainos_platform_tls_t* tls, void* value)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;
    int ret = pthread_setspecific(*(pthread_key_t*)tls->_pthread_key, value);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(ret);
}

void* ainos_platform_tls_get(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return NULL;
    return pthread_getspecific(*(pthread_key_t*)tls->_pthread_key);
}

/* ================================================================
 * 14. ÔøΩﬂ≥Ã≥ÔøΩ (Thread Pool) API
 * ================================================================ */

struct ainos_platform_threadpool {
    pthread_t* threads; int thread_count;
    int min_threads; int max_threads; int keepalive_ms;
    int is_running; int is_initialized; char name[64];
    struct { ainos_platform_threadpool_work_func_t func; void* arg; }* tasks;
    int task_capacity; int task_count; int task_head; int task_tail;
    pthread_mutex_t queue_mutex; pthread_cond_t queue_cond; pthread_cond_t empty_cond;
    int completed_tasks; int rejected_tasks;
};

static void* threadpool_worker(void* arg)
{
    ainos_platform_threadpool_t* pool = (ainos_platform_threadpool_t*)arg;
    pthread_mutex_lock(&pool->queue_mutex);
    while (pool->is_running) {
        while (pool->task_count == 0 && pool->is_running)
            pthread_cond_wait(&pool->queue_cond, &pool->queue_mutex);
        if (!pool->is_running) break;
        ainos_platform_threadpool_work_func_t func = pool->tasks[pool->task_head].func;
        void* targ = pool->tasks[pool->task_head].arg;
        pool->task_head = (pool->task_head + 1) % pool->task_capacity;
        pool->task_count--;
        pthread_mutex_unlock(&pool->queue_mutex);
        func(targ);
        pthread_mutex_lock(&pool->queue_mutex);
        pool->completed_tasks++;
        if (pool->task_count == 0) pthread_cond_broadcast(&pool->empty_cond);
    }
    pthread_mutex_unlock(&pool->queue_mutex);
    return NULL;
}

int ainos_platform_threadpool_create(ainos_platform_threadpool_t** pool,
                                     const ainos_platform_threadpool_config_t* config)
{
    if (!pool) return AINOS_PLATFORM_ERR_INVAL;
    ainos_platform_threadpool_t* tp = calloc(1, sizeof(ainos_platform_threadpool_t));
    if (!tp) return AINOS_PLATFORM_ERR_NOMEM;
    if (config) {
        tp->min_threads = config->min_threads; tp->max_threads = config->max_threads;
        tp->keepalive_ms = config->keepalive_ms;
        strncpy(tp->name, config->name, sizeof(tp->name) - 1);
    } else { tp->min_threads = 2; tp->max_threads = 8; tp->keepalive_ms = 60000; }
    tp->thread_count = tp->min_threads; tp->task_capacity = 4096;
    tp->is_running = 1; tp->is_initialized = 1;
    pthread_mutex_init(&tp->queue_mutex, NULL);
    pthread_cond_init(&tp->queue_cond, NULL);
    pthread_cond_init(&tp->empty_cond, NULL);
    tp->tasks = calloc(tp->task_capacity, sizeof(*tp->tasks));
    tp->threads = calloc(tp->thread_count, sizeof(pthread_t));
    if (!tp->tasks || !tp->threads) {
        free(tp->tasks); free(tp->threads); free(tp);
        return AINOS_PLATFORM_ERR_NOMEM;
    }
    for (int i = 0; i < tp->thread_count; i++)
        pthread_create(&tp->threads[i], NULL, threadpool_worker, tp);
    *pool = tp;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_submit(ainos_platform_threadpool_t* pool,
                                     ainos_platform_threadpool_work_func_t func, void* arg)
{
    if (!pool || !pool->is_initialized || !func) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock(&pool->queue_mutex);
    if (pool->task_count >= pool->task_capacity) {
        pool->rejected_tasks++;
        pthread_mutex_unlock(&pool->queue_mutex);
        return AINOS_PLATFORM_ERR_AGAIN;
    }
    pool->tasks[pool->task_tail].func = func;
    pool->tasks[pool->task_tail].arg = arg;
    pool->task_tail = (pool->task_tail + 1) % pool->task_capacity;
    pool->task_count++;
    pthread_cond_signal(&pool->queue_cond);
    pthread_mutex_unlock(&pool->queue_mutex);
    return AINOS_PLATFORM_OK;
}


int ainos_platform_threadpool_wait(ainos_platform_threadpool_t* pool)
{
    if (!pool || !pool->is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock(&pool->queue_mutex);
    while (pool->task_count > 0) pthread_cond_wait(&pool->empty_cond, &pool->queue_mutex);
    pthread_mutex_unlock(&pool->queue_mutex);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_get_stats(ainos_platform_threadpool_t* pool,
                                        ainos_platform_threadpool_stats_t* stats)
{
    if (!pool || !pool->is_initialized || !stats) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock(&pool->queue_mutex);
    stats->active_threads = pool->thread_count;
    stats->idle_threads = 0;
    stats->pending_tasks = pool->task_count;
    stats->completed_tasks = pool->completed_tasks;
    stats->rejected_tasks = pool->rejected_tasks;
    stats->total_threads = pool->thread_count;
    pthread_mutex_unlock(&pool->queue_mutex);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_destroy(ainos_platform_threadpool_t* pool)
{
    if (!pool || !pool->is_initialized) return AINOS_PLATFORM_ERR_INVAL;
    pthread_mutex_lock(&pool->queue_mutex);
    pool->is_running = 0;
    pthread_cond_broadcast(&pool->queue_cond);
    pthread_mutex_unlock(&pool->queue_mutex);
    for (int i = 0; i < pool->thread_count; i++) pthread_join(pool->threads[i], NULL);
    pthread_mutex_destroy(&pool->queue_mutex);
    pthread_cond_destroy(&pool->queue_cond);
    pthread_cond_destroy(&pool->empty_cond);
    free(pool->tasks); free(pool->threads);
    pool->is_initialized = 0; free(pool);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 16. Socket ÔøΩÔøΩ÷∑ÔøΩÔøΩÔøΩÔøΩ API
 * ================================================================ */

int ainos_platform_sockaddr_set_inet4(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in* sin = (struct sockaddr_in*)addr->_data;
    memset(sin, 0, sizeof(*sin));
    sin->sin_family = AF_INET; sin->sin_port = htons(port);
    if (ip) inet_pton(AF_INET, ip, &sin->sin_addr);
    else sin->sin_addr.s_addr = INADDR_ANY;
    addr->_len = sizeof(*sin);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_set_inet6(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in6* sin6 = (struct sockaddr_in6*)addr->_data;
    memset(sin6, 0, sizeof(*sin6));
    sin6->sin6_family = AF_INET6; sin6->sin6_port = htons(port);
    if (ip) inet_pton(AF_INET6, ip, &sin6->sin6_addr);
    else sin6->sin6_addr = in6addr_any;
    addr->_len = sizeof(*sin6);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_set_unix(ainos_platform_sockaddr_t* addr,
                                     const char* path)
{
    if (!addr || !path) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_un* sun = (struct sockaddr_un*)addr->_data;
    memset(sun, 0, sizeof(*sun));
    sun->sun_family = AF_UNIX;
    strncpy(sun->sun_path, path, sizeof(sun->sun_path) - 1);
    addr->_len = sizeof(*sun);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_get_family(const ainos_platform_sockaddr_t* addr)
{
    if (!addr) return AINOS_PLATFORM_AF_UNSPEC;
    struct sockaddr* sa = (struct sockaddr*)addr->_data;
    switch (sa->sa_family) {
        case AF_INET: return AINOS_PLATFORM_AF_INET;
        case AF_INET6: return AINOS_PLATFORM_AF_INET6;
        case AF_UNIX: return AINOS_PLATFORM_AF_UNIX;
        default: return AINOS_PLATFORM_AF_UNSPEC;
    }
}

int ainos_platform_sockaddr_get_inet4(const ainos_platform_sockaddr_t* addr,
                                      char* ip, int ip_len, uint16_t* port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in* sin = (struct sockaddr_in*)addr->_data;
    if (sin->sin_family != AF_INET) return AINOS_PLATFORM_ERR_INVAL;
    if (ip && ip_len > 0) inet_ntop(AF_INET, &sin->sin_addr, ip, (socklen_t)ip_len);
    if (port) *port = ntohs(sin->sin_port);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_get_inet6(const ainos_platform_sockaddr_t* addr,
                                      char* ip, int ip_len, uint16_t* port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;
    struct sockaddr_in6* sin6 = (struct sockaddr_in6*)addr->_data;
    if (sin6->sin6_family != AF_INET6) return AINOS_PLATFORM_ERR_INVAL;
    if (ip && ip_len > 0) inet_ntop(AF_INET6, &sin6->sin6_addr, ip, (socklen_t)ip_len);
    if (port) *port = ntohs(sin6->sin6_port);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dns_resolve(const char* hostname,
                               ainos_platform_sockaddr_t* addrs, int* addr_count)
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
        addrs[count]._len = rp->ai_addrlen;
        count++;
    }
    freeaddrinfo(result);
    *addr_count = count;
    return count > 0 ? AINOS_PLATFORM_OK : AINOS_PLATFORM_ERR_NOT_FOUND;
}


/* ================================================================
 * 17. ÔøΩƒºÔøΩ I/O API
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
    if (flags & AINOS_PLATFORM_FILE_O_DIRECTORY) f |= O_DIRECTORY;
    return f;
}

int ainos_platform_file_open(ainos_platform_file_t* file, const char* path, int flags, int mode)
{
    if (!file || !path) return AINOS_PLATFORM_ERR_INVAL;
    int f = file_flags_to_unix(flags);
    if (mode == 0) mode = 0644;
    int fd = open(path, f, mode);
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
    if (ret < 0) return -errno_to_platform(errno);
    return (int64_t)ret;
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

int ainos_platform_file_fstat(ainos_platform_file_t* file, ainos_platform_file_stat_t* stat)
{
    if (!file || !file->_is_valid || !stat) return AINOS_PLATFORM_ERR_INVAL;
    struct stat st;
    if (fstat(file->_fd, &st) < 0) return errno_to_platform(errno);
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

int ainos_platform_file_copy(const char* src, const char* dst)
{
    if (!src || !dst) return AINOS_PLATFORM_ERR_INVAL;
    int sfd = open(src, O_RDONLY);
    if (sfd < 0) return errno_to_platform(errno);
    int dfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (dfd < 0) { close(sfd); return errno_to_platform(errno); }
    char buf[65536]; ssize_t n;
    while ((n = read(sfd, buf, sizeof(buf))) > 0) {
        ssize_t written = 0;
        while (written < n) {
            ssize_t w = write(dfd, buf + written, (size_t)(n - written));
            if (w < 0) { close(sfd); close(dfd); return errno_to_platform(errno); }
            written += w;
        }
    }
    close(sfd); close(dfd);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_truncate(ainos_platform_file_t* file, int64_t length)
{
    if (!file || !file->_is_valid || length < 0) return AINOS_PLATFORM_ERR_INVAL;
    if (ftruncate(file->_fd, (off_t)length) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_sync(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (fsync(file->_fd) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_exists(const char* path)
{
    if (!path) return 0;
    return (access(path, F_OK) == 0);
}

int ainos_platform_file_permissions_string(int mode, char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    snprintf(buf, buf_size, %c%c%c%c%c%c%c%c%c,
             (mode & S_IRUSR) ? 'r' : '-', (mode & S_IWUSR) ? 'w' : '-',
             (mode & S_IXUSR) ? 'x' : '-', (mode & S_IRGRP) ? 'r' : '-',
             (mode & S_IWGRP) ? 'w' : '-', (mode & S_IXGRP) ? 'x' : '-',
             (mode & S_IROTH) ? 'r' : '-', (mode & S_IWOTH) ? 'w' : '-',
             (mode & S_IXOTH) ? 'x' : '-');
    return AINOS_PLATFORM_OK;
}


/* ================================================================
 * 18. ƒø¬ºÔøΩÔøΩÔøΩÔøΩ API
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
    entry->name[sizeof(entry->name) - 1] = ' ';
    char full[1024]; snprintf(full, sizeof(full), "%s/%s", dir->_path, entry->name);
    struct stat st;
    if (stat(full, &st) == 0) {
        entry->is_directory = S_ISDIR(st.st_mode);
        entry->is_regular = S_ISREG(st.st_mode);
        entry->size = (uint64_t)st.st_size;
    } else {
        entry->is_directory = (de->d_type == DT_DIR);
        entry->is_regular = (de->d_type == DT_REG);
        entry->size = 0;
    }
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

int ainos_platform_dir_mkdir_p(const char* path, int mode)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    char tmp[1024]; strncpy(tmp, path, sizeof(tmp) - 1); tmp[sizeof(tmp) - 1] = ' ';
    for (char* p = tmp + 1; *p; p++) {
        if (*p == '/') { char saved = *p; *p = ' '; mkdir(tmp, (mode_t)mode); *p = saved; }
    }
    mkdir(tmp, (mode_t)mode);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_rmdir(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    if (rmdir(path) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_rmdir_r(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    ainos_platform_dir_t dir;
    int ret = ainos_platform_dir_open(&dir, path);
    if (ret != AINOS_PLATFORM_OK) return ret;
    ainos_platform_dirent_t entry;
    while (ainos_platform_dir_read(&dir, &entry) > 0) {
        if (strcmp(entry.name, ".") == 0 || strcmp(entry.name, "..") == 0) continue;
        char child[1024]; snprintf(child, sizeof(child), "%s/%s", path, entry.name);
        if (entry.is_directory) ainos_platform_dir_rmdir_r(child);
        else ainos_platform_file_unlink(child);
    }
    ainos_platform_dir_close(&dir);
    return ainos_platform_dir_rmdir(path);
}

int ainos_platform_dir_getcwd(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (!getcwd(buf, buf_size)) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_chdir(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;
    if (chdir(path) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}


/* ================================================================
 * 19. ƒ⁄¥Êπ‹¿Ì API
 * ================================================================ */

void* ainos_platform_mem_alloc(size_t size) { return (size == 0) ? NULL : malloc(size); }
void* ainos_platform_mem_calloc(size_t num, size_t size) { return calloc(1, num * size); }
void* ainos_platform_mem_realloc(void* ptr, size_t new_size) {
    if (new_size == 0) { free(ptr); return NULL; } return realloc(ptr, new_size);
}
void ainos_platform_mem_free(void* ptr) { free(ptr); }

void* ainos_platform_mem_aligned_alloc(size_t alignment, size_t size) {
    if (alignment == 0 || (alignment & (alignment - 1)) != 0) return NULL;
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
    long pages = sysconf(_SC_AVPHYS_PAGES);
    long ps = sysconf(_SC_PAGESIZE);
    return (pages > 0 && ps > 0) ? (int64_t)pages * (int64_t)ps : -1;
}

int64_t ainos_platform_mem_get_total_physical_memory(void) {
    long pages = sysconf(_SC_PHYS_PAGES);
    long ps = sysconf(_SC_PAGESIZE);
    return (pages > 0 && ps > 0) ? (int64_t)pages * (int64_t)ps : -1;
}

int64_t ainos_platform_mem_get_process_memory(void) {
    FILE* f = fopen("/proc/self/status", "r");
    if (!f) return -1;
    int64_t rss = -1; char line[256];
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "VmRSS:", 6) == 0) {
            sscanf(line + 6, "%lld", &rss); rss *= 1024; break;
        }
    }
    fclose(f);
    return rss;
}

void* ainos_platform_mem_copy(void* d, const void* s, size_t n) { return memcpy(d, s, n); }
void* ainos_platform_mem_move(void* d, const void* s, size_t n) { return memmove(d, s, n); }
void* ainos_platform_mem_set(void* d, int v, size_t n) { return memset(d, v, n); }
int ainos_platform_mem_compare(const void* a, const void* b, size_t n) { return memcmp(a, b, n); }

int ainos_platform_mem_lock(const void* addr, size_t size) {
    if (!addr || size == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (mlock(addr, size) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mem_unlock(const void* addr, size_t size) {
    if (!addr || size == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (munlock(addr, size) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 20. π≤œÌƒ⁄¥Ê API
 * ================================================================ */

int ainos_platform_shm_create(ainos_platform_shm_t* shm, const char* name, size_t size, int create) {
    if (!shm || !name || size == 0) return AINOS_PLATFORM_ERR_INVAL;
    int oflags = create ? (O_CREAT | O_RDWR) : O_RDWR;
    int fd = shm_open(name, oflags, 0644);
    if (fd < 0) return errno_to_platform(errno);
    if (create) {
        if (ftruncate(fd, (off_t)size) < 0) { close(fd); return errno_to_platform(errno); }
    } else {
        struct stat st;
        if (fstat(fd, &st) < 0) { close(fd); return errno_to_platform(errno); }
        size = (size_t)st.st_size;
    }
    shm->_fd = fd; shm->_addr = NULL; shm->_size = size; shm->_is_valid = 1;
    strncpy(shm->_name, name, sizeof(shm->_name) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_map(ainos_platform_shm_t* shm) {
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (shm->_addr) return AINOS_PLATFORM_OK;
    shm->_addr = mmap(NULL, shm->_size, PROT_READ | PROT_WRITE, MAP_SHARED, shm->_fd, 0);
    if (shm->_addr == MAP_FAILED) { shm->_addr = NULL; return errno_to_platform(errno); }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_unmap(ainos_platform_shm_t* shm) {
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (shm->_addr) {
        if (munmap(shm->_addr, shm->_size) < 0) return errno_to_platform(errno);
        shm->_addr = NULL;
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_close(ainos_platform_shm_t* shm) {
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    ainos_platform_shm_unmap(shm); close(shm->_fd);
    shm->_fd = -1; shm->_is_valid = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_unlink(const char* name) {
    if (!name) return AINOS_PLATFORM_ERR_INVAL;
    if (shm_unlink(name) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

void* ainos_platform_shm_get_addr(const ainos_platform_shm_t* shm) {
    return (shm && shm->_is_valid) ? shm->_addr : NULL;
}

size_t ainos_platform_shm_get_size(const ainos_platform_shm_t* shm) {
    return (shm && shm->_is_valid) ? shm->_size : 0;
}


/* ================================================================
 * 21. ‘≠◊”≤Ÿ◊˜ API
 * ================================================================ */

void ainos_platform_atomic32_init(ainos_platform_atomic32_t* a, int32_t v) { if (a) __atomic_store_n(&a->_value, v, __ATOMIC_SEQ_CST); }
void ainos_platform_atomic64_init(ainos_platform_atomic64_t* a, int64_t v) { if (a) __atomic_store_n(&a->_value, v, __ATOMIC_SEQ_CST); }
int32_t ainos_platform_atomic32_load(ainos_platform_atomic32_t* a) { return a ? __atomic_load_n(&a->_value, __ATOMIC_SEQ_CST) : 0; }
int64_t ainos_platform_atomic64_load(ainos_platform_atomic64_t* a) { return a ? __atomic_load_n(&a->_value, __ATOMIC_SEQ_CST) : 0; }
void ainos_platform_atomic32_store(ainos_platform_atomic32_t* a, int32_t v) { if (a) __atomic_store_n(&a->_value, v, __ATOMIC_SEQ_CST); }
void ainos_platform_atomic64_store(ainos_platform_atomic64_t* a, int64_t v) { if (a) __atomic_store_n(&a->_value, v, __ATOMIC_SEQ_CST); }
int32_t ainos_platform_atomic32_exchange(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_exchange_n(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int64_t ainos_platform_atomic64_exchange(ainos_platform_atomic64_t* a, int64_t v) { return a ? __atomic_exchange_n(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int32_t ainos_platform_atomic32_compare_exchange(ainos_platform_atomic32_t* a, int32_t e, int32_t d) {
    if (!a) return 0; __atomic_compare_exchange_n(&a->_value, &e, d, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); return e;
}
int64_t ainos_platform_atomic64_compare_exchange(ainos_platform_atomic64_t* a, int64_t e, int64_t d) {
    if (!a) return 0; __atomic_compare_exchange_n(&a->_value, &e, d, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST); return e;
}
int32_t ainos_platform_atomic32_fetch_add(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_fetch_add(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int64_t ainos_platform_atomic64_fetch_add(ainos_platform_atomic64_t* a, int64_t v) { return a ? __atomic_fetch_add(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int32_t ainos_platform_atomic32_fetch_sub(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_fetch_sub(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int64_t ainos_platform_atomic64_fetch_sub(ainos_platform_atomic64_t* a, int64_t v) { return a ? __atomic_fetch_sub(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int32_t ainos_platform_atomic32_fetch_and(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_fetch_and(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int32_t ainos_platform_atomic32_fetch_or(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_fetch_or(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }
int32_t ainos_platform_atomic32_fetch_xor(ainos_platform_atomic32_t* a, int32_t v) { return a ? __atomic_fetch_xor(&a->_value, v, __ATOMIC_SEQ_CST) : 0; }

/* ================================================================
 * 22.  ±º‰ API
 * ================================================================ */

int ainos_platform_time_now(ainos_platform_time_t* t) {
    if (!t) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    t->seconds = (int64_t)ts.tv_sec; t->nanoseconds = (int64_t)ts.tv_nsec;
    struct timespec mono; clock_gettime(CLOCK_MONOTONIC, &mono);
    t->raw_counter = (int64_t)mono.tv_sec * 1000000000LL + (int64_t)mono.tv_nsec;
    t->raw_frequency = 1000000000LL;
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_now_ms(void) {
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000LL + (int64_t)ts.tv_nsec / 1000000;
}

int64_t ainos_platform_time_monotonic_ns(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + (int64_t)ts.tv_nsec;
}

int ainos_platform_time_get_raw_counter(int64_t* v) {
    if (!v) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    *v = (int64_t)ts.tv_sec * 1000000000LL + (int64_t)ts.tv_nsec;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_get_raw_frequency(int64_t* freq) {
    if (!freq) return AINOS_PLATFORM_ERR_INVAL;
    *freq = 1000000000LL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_sleep_ms(int ms) {
    if (ms < 0) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };
    int ret; do { ret = nanosleep(&ts, &ts); } while (ret != 0 && errno == EINTR);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_time_sleep_us(int us) {
    if (us < 0) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts = { us / 1000000, (us % 1000000) * 1000L };
    int ret; do { ret = nanosleep(&ts, &ts); } while (ret != 0 && errno == EINTR);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int ainos_platform_time_sleep_ns(int64_t ns) {
    if (ns < 0) return AINOS_PLATFORM_ERR_INVAL;
    struct timespec ts = { ns / 1000000000LL, (long)(ns % 1000000000LL) };
    int ret; do { ret = nanosleep(&ts, &ts); } while (ret != 0 && errno == EINTR);
    return (ret == 0) ? AINOS_PLATFORM_OK : errno_to_platform(errno);
}

int64_t ainos_platform_time_get_tick_count(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000LL + (int64_t)ts.tv_nsec / 1000000;
}


int ainos_platform_time_format(const ainos_platform_time_t* t, const char* fmt, char* buf, size_t buf_size) {
    if (!t || !fmt || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    time_t sec = (time_t)t->seconds;
    struct tm* tm_info = localtime(&sec);
    if (!tm_info) { buf[0] = ' '; return AINOS_PLATFORM_ERR_GENERAL; }
    if (strftime(buf, buf_size, fmt, tm_info) == 0) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_format_iso8601(char* buf, size_t buf_size) {
    if (!buf || buf_size < 25) return AINOS_PLATFORM_ERR_INVAL;
    ainos_platform_time_t t; ainos_platform_time_now(&t);
    time_t sec = (time_t)t.seconds;
    struct tm* tm_info = localtime(&sec);
    if (!tm_info) { buf[0] = ' '; return AINOS_PLATFORM_ERR_GENERAL; }
    int ms = (int)(t.nanoseconds / 1000000);
    strftime(buf, buf_size, "%Y-%m-%dT%H:%M:%S", tm_info);
    int len = (int)strlen(buf);
    snprintf(buf + len, buf_size - len, ".%03dZ", ms);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_diff_ns(const ainos_platform_time_t* t1, const ainos_platform_time_t* t2) {
    if (!t1 || !t2) return 0;
    return (t1->seconds - t2->seconds) * 1000000000LL + (t1->nanoseconds - t2->nanoseconds);
}

int64_t ainos_platform_time_diff_ms(const ainos_platform_time_t* t1, const ainos_platform_time_t* t2) {
    if (!t1 || !t2) return 0;
    return (t1->seconds - t2->seconds) * 1000LL + (t1->nanoseconds - t2->nanoseconds) / 1000000;
}

void ainos_platform_time_add(ainos_platform_time_t* result, const ainos_platform_time_t* t, const ainos_platform_duration_t* d) {
    if (!result || !t || !d) return;
    result->seconds = t->seconds + d->seconds;
    result->nanoseconds = t->nanoseconds + d->nanoseconds;
    if (result->nanoseconds >= 1000000000LL) { result->seconds++; result->nanoseconds -= 1000000000LL; }
    result->raw_counter = t->raw_counter; result->raw_frequency = t->raw_frequency;
}

void ainos_platform_time_sub(ainos_platform_time_t* result, const ainos_platform_time_t* t, const ainos_platform_duration_t* d) {
    if (!result || !t || !d) return;
    result->seconds = t->seconds - d->seconds;
    result->nanoseconds = t->nanoseconds - d->nanoseconds;
    if (result->nanoseconds < 0) { result->seconds--; result->nanoseconds += 1000000000LL; }
    result->raw_counter = t->raw_counter; result->raw_frequency = t->raw_frequency;
}

int ainos_platform_time_compare(const ainos_platform_time_t* t1, const ainos_platform_time_t* t2) {
    if (!t1 || !t2) return 0;
    if (t1->seconds < t2->seconds) return -1;
    if (t1->seconds > t2->seconds) return 1;
    if (t1->nanoseconds < t2->nanoseconds) return -1;
    if (t1->nanoseconds > t2->nanoseconds) return 1;
    return 0;
}

void ainos_platform_time_from_unix(ainos_platform_time_t* t, int64_t seconds, int64_t nanoseconds) {
    if (!t) return;
    t->seconds = seconds; t->nanoseconds = nanoseconds; t->raw_counter = 0; t->raw_frequency = 0;
}


/* ================================================================
 * 23. Ω¯≥Ãπ‹¿Ì API
 * ================================================================ */

int ainos_platform_process_spawn(ainos_platform_process_t* process, const char* path,
                                 char* const argv[], int flags) {
    if (!process || !path) return AINOS_PLATFORM_ERR_INVAL;
    int stdin_pipe[2] = {-1, -1}, stdout_pipe[2] = {-1, -1}, stderr_pipe[2] = {-1, -1};
    if (flags & AINOS_PLATFORM_PROCESS_REDIRECT_STDIO) {
        if (pipe(stdin_pipe) < 0 || pipe(stdout_pipe) < 0 || pipe(stderr_pipe) < 0)
            return errno_to_platform(errno);
    }
    pid_t pid = fork();
    if (pid < 0) return errno_to_platform(errno);
    if (pid == 0) {
        if (flags & AINOS_PLATFORM_PROCESS_REDIRECT_STDIO) {
            close(stdin_pipe[1]); dup2(stdin_pipe[0], 0);
            close(stdout_pipe[0]); dup2(stdout_pipe[1], 1);
            close(stderr_pipe[0]); dup2(stderr_pipe[1], 2);
        }
        if (flags & AINOS_PLATFORM_PROCESS_NEW_PGROUP) setpgid(0, 0);
        if (flags & AINOS_PLATFORM_PROCESS_LOW_PRIORITY) nice(10);
        if (flags & AINOS_PLATFORM_PROCESS_SEARCH_PATH) execvp(path, argv);
        else execv(path, argv);
        _exit(127);
    }
    if (flags & AINOS_PLATFORM_PROCESS_REDIRECT_STDIO) {
        close(stdin_pipe[0]); close(stdout_pipe[1]); close(stderr_pipe[1]);
        process->_stdin_fd = stdin_pipe[1]; process->_stdout_fd = stdout_pipe[0];
        process->_stderr_fd = stderr_pipe[0];
    } else { process->_stdin_fd = -1; process->_stdout_fd = -1; process->_stderr_fd = -1; }
    process->_pid = pid; process->_is_valid = 1; process->_exit_code = 0;
    process->_has_exited = 0; process->_waitpid_called = 0;
    if (flags & AINOS_PLATFORM_PROCESS_DETACHED) signal(SIGCHLD, SIG_IGN);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_wait(ainos_platform_process_t* process, int* exit_code) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    int status; pid_t ret = waitpid(process->_pid, &status, 0);
    if (ret < 0) return errno_to_platform(errno);
    process->_has_exited = 1; process->_waitpid_called = 1;
    if (WIFEXITED(status)) process->_exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status)) process->_exit_code = -WTERMSIG(status);
    if (exit_code) *exit_code = process->_exit_code;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_wait_timeout(ainos_platform_process_t* process, int* exit_code, int timeout_ms) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (timeout_ms < 0) return ainos_platform_process_wait(process, exit_code);
    int elapsed = 0;
    while (elapsed < timeout_ms) {
        int status; pid_t ret = waitpid(process->_pid, &status, WNOHANG);
        if (ret < 0) return errno_to_platform(errno);
        if (ret > 0) {
            process->_has_exited = 1; process->_waitpid_called = 1;
            if (WIFEXITED(status)) process->_exit_code = WEXITSTATUS(status);
            else if (WIFSIGNALED(status)) process->_exit_code = -WTERMSIG(status);
            if (exit_code) *exit_code = process->_exit_code;
            return AINOS_PLATFORM_OK;
        }
        struct timespec ts = {0, 10000000}; nanosleep(&ts, NULL); elapsed += 10;
    }
    return AINOS_PLATFORM_ERR_TIMEOUT;
}

int ainos_platform_process_kill(ainos_platform_process_t* process) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (kill(process->_pid, SIGKILL) < 0) return errno_to_platform(errno);
    process->_has_exited = 1; return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_pid(void) { return (int)getpid(); }

int ainos_platform_process_get_name(char* name, size_t name_size) {
    if (!name || name_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    FILE* f = fopen("/proc/self/comm", "r");
    if (f) {
        if (fgets(name, (int)name_size, f)) {
            size_t len = strlen(name);
            if (len > 0 && name[len-1] == '
') name[len-1] = ' ';
        }
        fclose(f); return AINOS_PLATFORM_OK;
    }
    snprintf(name, name_size, "unknown");
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_process_get_path(char* path, size_t path_size) {
    if (!path || path_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    ssize_t len = readlink("/proc/self/exe", path, path_size - 1);
    if (len < 0) return errno_to_platform(errno);
    path[len] = ' '; return AINOS_PLATFORM_OK;
}

int ainos_platform_process_is_running(ainos_platform_process_t* process) {
    if (!process || !process->_is_valid) return 0;
    if (process->_has_exited) return 0;
    int status; pid_t ret = waitpid(process->_pid, &status, WNOHANG);
    if (ret < 0) return 0;
    if (ret > 0) { process->_has_exited = 1; return 0; }
    return 1;
}

int ainos_platform_process_signal(ainos_platform_process_t* process, int signal) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (kill(process->_pid, signal) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_enum(ainos_platform_process_enum_cb_t callback, void* arg) {
    if (!callback) return AINOS_PLATFORM_ERR_INVAL;
    DIR* proc = opendir("/proc");
    if (!proc) return AINOS_PLATFORM_ERR_NOT_FOUND;
    struct dirent* entry;
    while ((entry = readdir(proc)) != NULL) {
        if (entry->d_type != DT_DIR) continue;
        int pid = atoi(entry->d_name);
        if (pid <= 0) continue;
        char name[256] = {0}; char comm[512];
        snprintf(comm, sizeof(comm), "/proc/%d/comm", pid);
        FILE* f = fopen(comm, "r");
        if (f) {
            fgets(name, sizeof(name), f); size_t len = strlen(name);
            if (len > 0 && name[len-1] == '
') name[len-1] = ' ';
            fclose(f);
        }
        int ret = callback(pid, name, arg);
        if (ret != 0) { closedir(proc); return AINOS_PLATFORM_OK; }
    }
    closedir(proc); return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_exit_code(ainos_platform_process_t* process, int* exit_code) {
    if (!process || !exit_code) return AINOS_PLATFORM_ERR_INVAL;
    if (!process->_has_exited) return AINOS_PLATFORM_ERR_BUSY;
    *exit_code = process->_exit_code; return AINOS_PLATFORM_OK;
}

int ainos_platform_process_destroy(ainos_platform_process_t* process) {
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (!process->_has_exited && !process->_waitpid_called) waitpid(process->_pid, NULL, WNOHANG);
    if (process->_stdin_fd >= 0) close(process->_stdin_fd);
    if (process->_stdout_fd >= 0) close(process->_stdout_fd);
    if (process->_stderr_fd >= 0) close(process->_stderr_fd);
    memset(process, 0, sizeof(*process)); return AINOS_PLATFORM_OK;
}


/* ================================================================
 * 24. ∂ØÃ¨ø‚º”‘ÿ API
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
    if (!lib || !lib->_is_valid || !symbol) return NULL;
    return dlsym(lib->_handle, symbol);
}

int ainos_platform_dlclose(ainos_platform_library_t* lib) {
    if (!lib || !lib->_is_valid) return AINOS_PLATFORM_ERR_INVAL;
    if (dlclose(lib->_handle) != 0) return AINOS_PLATFORM_ERR_GENERAL;
    lib->_is_valid = 0; lib->_handle = NULL; return AINOS_PLATFORM_OK;
}

const char* ainos_platform_dlerror(void) { return dlerror(); }

int ainos_platform_dlget_self_path(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    Dl_info info;
    if (dladdr((void*)ainos_platform_dlget_self_path, &info) && info.dli_fname) {
        strncpy(buf, info.dli_fname, buf_size - 1); buf[buf_size - 1] = ' ';
        return AINOS_PLATFORM_OK;
    }
    return ainos_platform_process_get_path(buf, buf_size);
}

/* ================================================================
 * 25. ª∑æ≥±‰¡ø API
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

int ainos_platform_get_all_env(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    extern char** environ; int pos = 0;
    for (char** env = environ; *env && pos < (int)buf_size - 1; env++) {
        int len = (int)strlen(*env);
        int copy = (len < (int)(buf_size - pos)) ? len : (int)(buf_size - pos - 1);
        memcpy(buf + pos, *env, copy); pos += copy;
        if (pos < (int)buf_size - 1) buf[pos++] = '
';
    }
    if (pos < (int)buf_size) buf[pos] = ' ';
    return pos;
}

/* ================================================================
 * 26. ¥ÌŒÛ¥¶¿Ì API
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

const char* ainos_platform_get_last_error_string(void) { return ainos_platform_strerror(g_last_error); }
void ainos_platform_set_last_error(int err) { g_last_error = err; }

int ainos_platform_strerror_r(int err, char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    const char* msg = ainos_platform_strerror(err);
    strncpy(buf, msg, buf_size - 1); buf[buf_size - 1] = ' ';
    return AINOS_PLATFORM_OK;
}


/* ================================================================
 * 27. œµÕ≥–≈œ¢ API
 * ================================================================ */

int ainos_platform_sys_get_cpu_info(ainos_platform_cpu_info_t* info) {
    if (!info) return AINOS_PLATFORM_ERR_INVAL;
    memset(info, 0, sizeof(*info));
    info->logical_cores = (int)sysconf(_SC_NPROCESSORS_ONLN);
    info->is_64bit = (sizeof(void*) == 8); info->cache_line_size = 64;
    FILE* f = fopen("/proc/cpuinfo", "r");
    if (f) {
        char line[256]; int core_count = 0;
        while (fgets(line, sizeof(line), f)) {
            if (strncmp(line, "processor", 9) == 0) info->physical_cores++;
            if (strncmp(line, "cpu cores", 9) == 0) {
                int val = 0; sscanf(line, "cpu cores	: %d", &val);
                if (val > 0) core_count = val;
            }
            if (strncmp(line, "model name", 10) == 0) {
                char* colon = strchr(line, ':');
                if (colon) {
                    colon++; while (*colon == ' ' || *colon == '	') colon++;
                    strncpy(info->name, colon, sizeof(info->name) - 1);
                    size_t len = strlen(info->name);
                    if (len > 0 && info->name[len-1] == '
') info->name[len-1] = ' ';
                }
            }
            if (strncmp(line, "cache size", 10) == 0) {
                int val = 0; sscanf(line, "cache size	: %d", &val); info->l3_cache = val;
            }
            if (strncmp(line, "flags", 5) == 0) {
                if (strstr(line, "avx2")) info->has_avx2 = 1;
                if (strstr(line, "avx512")) info->has_avx512 = 1;
                if (strstr(line, "avx")) info->has_avx = 1;
            }
        }
        fclose(f);
        if (core_count > 0) info->physical_cores = core_count;
    }
    if (info->physical_cores == 0) info->physical_cores = info->logical_cores;
    info->l1d_cache = 32; info->l1i_cache = 32; info->l2_cache = 256;
    if (info->l3_cache == 0) info->l3_cache = 8192;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_load(ainos_platform_system_load_t* load) {
    if (!load) return AINOS_PLATFORM_ERR_INVAL;
    memset(load, 0, sizeof(*load));
    double loadavg[3] = {0};
    if (getloadavg(loadavg, 3) >= 0) { load->load_1m = loadavg[0]; load->load_5m = loadavg[1]; load->load_15m = loadavg[2]; }
    struct sysinfo si;
    if (sysinfo(&si) == 0) {
        load->total_memory = (int64_t)si.totalram * si.mem_unit;
        load->free_memory = (int64_t)si.freeram * si.mem_unit;
        load->used_memory = load->total_memory - load->free_memory;
        if (load->total_memory > 0) load->memory_usage_percent = (double)load->used_memory / (double)load->total_memory * 100.0;
        load->total_swap = (int64_t)si.totalswap * si.mem_unit;
        load->free_swap = (int64_t)si.freeswap * si.mem_unit;
    }
    static unsigned long long prev_idle = 0, prev_total = 0;
    FILE* f = fopen("/proc/stat", "r");
    if (f) {
        char line[256];
        if (fgets(line, sizeof(line), f)) {
            unsigned long long user, nice, sys, idle, iowait, irq, softirq, steal;
            sscanf(line, "cpu %llu %llu %llu %llu %llu %llu %llu %llu",
                   &user, &nice, &sys, &idle, &iowait, &irq, &softirq, &steal);
            unsigned long long total = user + nice + sys + idle + iowait + irq + softirq + steal;
            if (prev_total > 0) {
                unsigned long long d_idle = idle - prev_idle;
                unsigned long long d_total = total - prev_total;
                if (d_total > 0) load->cpu_usage_percent = 100.0 - (double)d_idle / (double)d_total * 100.0;
            }
            prev_idle = idle; prev_total = total;
        }
        fclose(f);
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_hostname(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (gethostname(buf, buf_size) < 0) return errno_to_platform(errno);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_os_info(char* os_name, size_t name_size, char* os_version, size_t ver_size) {
    struct utsname uts;
    if (uname(&uts) < 0) return AINOS_PLATFORM_ERR_GENERAL;
    if (os_name) snprintf(os_name, name_size, "%s", uts.sysname);
    if (os_version) snprintf(os_version, ver_size, "%s %s", uts.release, uts.version);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_sys_get_uptime(void) {
    struct sysinfo si;
    if (sysinfo(&si) == 0) return (int64_t)si.uptime;
    return -1;
}

int ainos_platform_sys_get_timezone(char* buf, size_t buf_size) {
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    time_t now = time(NULL); struct tm* tm_info = localtime(&now);
    if (tm_info) { strncpy(buf, tm_info->tm_zone, buf_size - 1); buf[buf_size - 1] = ' '; return AINOS_PLATFORM_OK; }
    return AINOS_PLATFORM_ERR_GENERAL;
}


/* ================================================================
 * 28. øÿ÷∆Ã®/÷’∂À API
 * ================================================================ */

int ainos_platform_console_set_color(int color) {
    if (!isatty(STDOUT_FILENO)) return AINOS_PLATFORM_ERR_NOT_SUP;
    const char* code = NULL;
    switch (color) {
        case AINOS_PLATFORM_COLOR_RESET: code = "[0m"; break;
        case AINOS_PLATFORM_COLOR_RED: code = "[31m"; break;
        case AINOS_PLATFORM_COLOR_GREEN: code = "[32m"; break;
        case AINOS_PLATFORM_COLOR_YELLOW: code = "[33m"; break;
        case AINOS_PLATFORM_COLOR_BLUE: code = "[34m"; break;
        case AINOS_PLATFORM_COLOR_MAGENTA: code = "[35m"; break;
        case AINOS_PLATFORM_COLOR_CYAN: code = "[36m"; break;
        case AINOS_PLATFORM_COLOR_WHITE: code = "[37m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_RED: code = "[91m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_GREEN: code = "[92m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_YELLOW: code = "[93m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_BLUE: code = "[94m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_MAGENTA: code = "[95m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_CYAN: code = "[96m"; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_WHITE: code = "[97m"; break;
    }
    if (code) { write(STDOUT_FILENO, code, strlen(code)); return AINOS_PLATFORM_OK; }
    return AINOS_PLATFORM_ERR_INVAL;
}

int ainos_platform_console_reset_color(void) { return ainos_platform_console_set_color(AINOS_PLATFORM_COLOR_RESET); }

int ainos_platform_console_get_width(void) {
    struct winsize ws;
    if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == 0) return ws.ws_col;
    char* env = getenv("COLUMNS"); return env ? atoi(env) : 80;
}

int ainos_platform_console_get_height(void) {
    struct winsize ws;
    if (ioctl(STDOUT_FILENO, TIOCGWINSZ, &ws) == 0) return ws.ws_row;
    char* env = getenv("LINES"); return env ? atoi(env) : 25;
}

int ainos_platform_console_has_color(void) {
    if (!isatty(STDOUT_FILENO)) return 0;
    char* term = getenv("TERM");
    return term && (strstr(term, "color") || strstr(term, "xterm") || strstr(term, "rxvt") || strstr(term, "screen")) ? 1 : 0;
}

/* ================================================================
 * 29. »’÷æ API
 * ================================================================ */

static ainos_platform_log_func_t g_log_callback = NULL;
static void* g_log_user_data = NULL;
static int g_log_level = AINOS_PLATFORM_LOG_INFO;

static const char* log_level_string(int level) {
    switch (level) {
        case AINOS_PLATFORM_LOG_DEBUG: return "DEBUG";
        case AINOS_PLATFORM_LOG_INFO: return "INFO";
        case AINOS_PLATFORM_LOG_WARN: return "WARN";
        case AINOS_PLATFORM_LOG_ERROR: return "ERROR";
        case AINOS_PLATFORM_LOG_FATAL: return "FATAL";
        default: return "UNKNOWN";
    }
}

void ainos_platform_log_set_callback(ainos_platform_log_func_t callback, void* user_data) {
    g_log_callback = callback; g_log_user_data = user_data;
}

void ainos_platform_log_set_level(int level) { g_log_level = level; }

void ainos_platform_log_write(int level, const char* file, int line, const char* func, const char* fmt, ...) {
    if (level < g_log_level) return;
    char msg[4096]; va_list args;
    va_start(args, fmt); vsnprintf(msg, sizeof(msg), fmt, args); va_end(args);
    char timestamp[64]; ainos_platform_time_t now;
    ainos_platform_time_now(&now);
    ainos_platform_time_format(&now, "%Y-%m-%d %H:%M:%S", timestamp, sizeof(timestamp));
    char formatted[8192];
    snprintf(formatted, sizeof(formatted), "[%s] %-5s %s:%d (%s) %s", timestamp, log_level_string(level), file, line, func, msg);
    if (g_log_callback) g_log_callback(level, formatted, g_log_user_data);
    else fprintf(stderr, "%s
", formatted);
}


/* ================================================================
 * 30. UUID …˙≥… API
 * ================================================================ */

int ainos_platform_uuid_v4_generate(char* buf, size_t buf_size) {
    if (!buf || buf_size < 37) return AINOS_PLATFORM_ERR_INVAL;
    uuid_t uuid; uuid_generate_random(uuid);
    uuid_unparse_lower(uuid, buf);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 31. ◊÷∑˚¥Æπ§æﬂ API
 * ================================================================ */

int ainos_platform_wchar_to_utf8(const wchar_t* wstr, char* buf, size_t buf_size) {
    if (!wstr || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    size_t ret = wcstombs(buf, wstr, buf_size);
    if (ret == (size_t)-1) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_utf8_to_wchar(const char* utf8, wchar_t* buf, size_t buf_size) {
    if (!utf8 || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    size_t ret = mbstowcs(buf, utf8, buf_size);
    if (ret == (size_t)-1) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_strerror_locale(int err, char* buf, size_t buf_size, const char* locale) {
    (void)locale;
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;
    const char* msg = strerror(err);
    strncpy(buf, msg, buf_size - 1); buf[buf_size - 1] = ' ';
    return AINOS_PLATFORM_OK;
}
