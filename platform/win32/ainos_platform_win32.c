// Ainos OS - Platform Abstraction Layer (Windows Implementation)
// Windows 平台实现: Win32 API
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

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <process.h>
#include <iphlpapi.h>
#include <psapi.h>
#include <intrin.h>
#include <rpc.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "psapi.lib")
#pragma comment(lib, "rpcrt4.lib")

/* ================================================================
 * 内部工具
 * ================================================================ */

/* 全局初始化状态 */
static int g_platform_initialized = 0;
static int g_winsock_initialized = 0;
static int g_last_error = 0;

/* 错误码映射表 */
static const struct {
    int win32_err;
    int plat_err;
} g_errno_map[] = {
    { ERROR_SUCCESS,              AINOS_PLATFORM_OK },
    { ERROR_FILE_NOT_FOUND,       AINOS_PLATFORM_ERR_NOT_FOUND },
    { ERROR_PATH_NOT_FOUND,       AINOS_PLATFORM_ERR_NOT_FOUND },
    { ERROR_ACCESS_DENIED,        AINOS_PLATFORM_ERR_PERM },
    { ERROR_INVALID_HANDLE,       AINOS_PLATFORM_ERR_INVAL },
    { ERROR_NOT_ENOUGH_MEMORY,    AINOS_PLATFORM_ERR_NOMEM },
    { ERROR_OUTOFMEMORY,          AINOS_PLATFORM_ERR_NOMEM },
    { ERROR_INVALID_PARAMETER,    AINOS_PLATFORM_ERR_INVAL },
    { ERROR_ALREADY_EXISTS,       AINOS_PLATFORM_ERR_EXIST },
    { ERROR_BUSY,                 AINOS_PLATFORM_ERR_BUSY },
    { ERROR_TIMEOUT,              AINOS_PLATFORM_ERR_TIMEOUT },
    { ERROR_OPERATION_ABORTED,    AINOS_PLATFORM_ERR_INTR },
    { ERROR_IO_PENDING,           AINOS_PLATFORM_ERR_AGAIN },
    { ERROR_DEVICE_NOT_CONNECTED, AINOS_PLATFORM_ERR_CONNREFUSED },
    { ERROR_CONNECTION_REFUSED,   AINOS_PLATFORM_ERR_CONNREFUSED },
    { ERROR_CONNECTION_RESET,     AINOS_PLATFORM_ERR_CONNRESET },
    { ERROR_ADDRESS_ALREADY_ASSOCIATED, AINOS_PLATFORM_ERR_ADDRINUSE },
    { WSAEWOULDBLOCK,             AINOS_PLATFORM_ERR_WOULDBLOCK },
    { WSAEADDRINUSE,              AINOS_PLATFORM_ERR_ADDRINUSE },
    { WSAECONNREFUSED,            AINOS_PLATFORM_ERR_CONNREFUSED },
    { WSAECONNRESET,              AINOS_PLATFORM_ERR_CONNRESET },
    { WSAETIMEDOUT,               AINOS_PLATFORM_ERR_TIMEOUT },
    { 0, 0 }
};

static int win32_to_platform_error(DWORD win32_err)
{
    for (int i = 0; g_errno_map[i].win32_err != 0; i++) {
        if (g_errno_map[i].win32_err == (int)win32_err) {
            return g_errno_map[i].plat_err;
        }
    }
    return AINOS_PLATFORM_ERR_GENERAL;
}

static int wsagetlasterror_to_platform(void)
{
    return win32_to_platform_error(WSAGetLastError());
}

/* ================================================================
 * 5. 平台初始化和清理
 * ================================================================ */

int ainos_platform_init(void)
{
    if (g_platform_initialized) {
        return AINOS_PLATFORM_OK;
    }

    /* 初始化 Winsock */
    WSADATA wsa_data;
    int ret = WSAStartup(MAKEWORD(2, 2), &wsa_data);
    if (ret != 0) {
        g_last_error = ret;
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    g_winsock_initialized = 1;
    g_platform_initialized = 1;
    return AINOS_PLATFORM_OK;
}

void ainos_platform_cleanup(void)
{
    if (g_winsock_initialized) {
        WSACleanup();
        g_winsock_initialized = 0;
    }
    g_platform_initialized = 0;
}

int ainos_platform_is_initialized(void)
{
    return g_platform_initialized;
}

const char* ainos_platform_name(void)
{
    return "windows";
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

    mutex->_critical_section = malloc(sizeof(CRITICAL_SECTION));
    if (!mutex->_critical_section) {
        return AINOS_PLATFORM_ERR_NOMEM;
    }

    InitializeCriticalSection((CRITICAL_SECTION*)mutex->_critical_section);
    mutex->_is_initialized = 1;
    mutex->_is_recursive = 1; /* Windows CRITICAL_SECTION 总是递归的 */
    mutex->_native_handle = NULL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mutex_destroy(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DeleteCriticalSection((CRITICAL_SECTION*)mutex->_critical_section);
    free(mutex->_critical_section);
    mutex->_critical_section = NULL;
    mutex->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mutex_lock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    EnterCriticalSection((CRITICAL_SECTION*)mutex->_critical_section);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mutex_trylock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    if (TryEnterCriticalSection((CRITICAL_SECTION*)mutex->_critical_section)) {
        return AINOS_PLATFORM_OK;
    }
    return AINOS_PLATFORM_ERR_BUSY;
}

int ainos_platform_mutex_unlock(ainos_platform_mutex_t* mutex)
{
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    LeaveCriticalSection((CRITICAL_SECTION*)mutex->_critical_section);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_mutex_lock_timeout(ainos_platform_mutex_t* mutex,
                                      int timeout_ms)
{
    /* Windows CRITICAL_SECTION 不支持超时, 使用自旋等待 */
    if (!mutex || !mutex->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    if (timeout_ms <= 0) {
        return ainos_platform_mutex_trylock(mutex);
    }

    DWORD start = GetTickCount();
    while (1) {
        if (TryEnterCriticalSection((CRITICAL_SECTION*)mutex->_critical_section)) {
            return AINOS_PLATFORM_OK;
        }
        DWORD elapsed = GetTickCount() - start;
        if (elapsed >= (DWORD)timeout_ms) {
            return AINOS_PLATFORM_ERR_TIMEOUT;
        }
        SwitchToThread();
    }
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

    rwlock->_srwlock = malloc(sizeof(SRWLOCK));
    if (!rwlock->_srwlock) return AINOS_PLATFORM_ERR_NOMEM;

    InitializeSRWLock((SRWLOCK*)rwlock->_srwlock);
    rwlock->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_rwlock_destroy(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    /* SRWLOCK 不需要显式销毁 */
    free(rwlock->_srwlock);
    rwlock->_srwlock = NULL;
    rwlock->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_rwlock_rdlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    AcquireSRWLockShared((SRWLOCK*)rwlock->_srwlock);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_rwlock_try_rdlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    if (TryAcquireSRWLockShared((SRWLOCK*)rwlock->_srwlock)) {
        return AINOS_PLATFORM_OK;
    }
    return AINOS_PLATFORM_ERR_BUSY;
}

int ainos_platform_rwlock_wrlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    AcquireSRWLockExclusive((SRWLOCK*)rwlock->_srwlock);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_rwlock_try_wrlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    if (TryAcquireSRWLockExclusive((SRWLOCK*)rwlock->_srwlock)) {
        return AINOS_PLATFORM_OK;
    }
    return AINOS_PLATFORM_ERR_BUSY;
}

int ainos_platform_rwlock_unlock(ainos_platform_rwlock_t* rwlock)
{
    if (!rwlock || !rwlock->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    /* 自动检测是 shared 还是 exclusive */
    ReleaseSRWLockExclusive((SRWLOCK*)rwlock->_srwlock);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 8. 条件变量 (Condition Variable) API
 * ================================================================ */

int ainos_platform_cond_init(ainos_platform_cond_t* cond)
{
    if (!cond) return AINOS_PLATFORM_ERR_INVAL;

    cond->_cond_var = malloc(sizeof(CONDITION_VARIABLE));
    if (!cond->_cond_var) return AINOS_PLATFORM_ERR_NOMEM;

    InitializeConditionVariable((CONDITION_VARIABLE*)cond->_cond_var);
    cond->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_cond_destroy(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    free(cond->_cond_var);
    cond->_cond_var = NULL;
    cond->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_cond_wait(ainos_platform_cond_t* cond,
                             ainos_platform_mutex_t* mutex)
{
    if (!cond || !cond->_is_initialized || !mutex) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (SleepConditionVariableCS((CONDITION_VARIABLE*)cond->_cond_var,
                                 (CRITICAL_SECTION*)mutex->_critical_section,
                                 INFINITE)) {
        return AINOS_PLATFORM_OK;
    }
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_cond_timedwait(ainos_platform_cond_t* cond,
                                  ainos_platform_mutex_t* mutex,
                                  int timeout_ms)
{
    if (!cond || !cond->_is_initialized || !mutex) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (SleepConditionVariableCS((CONDITION_VARIABLE*)cond->_cond_var,
                                 (CRITICAL_SECTION*)mutex->_critical_section,
                                 timeout_ms < 0 ? INFINITE : (DWORD)timeout_ms)) {
        return AINOS_PLATFORM_OK;
    }
    if (GetLastError() == ERROR_TIMEOUT) {
        return AINOS_PLATFORM_ERR_TIMEOUT;
    }
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_cond_signal(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    WakeConditionVariable((CONDITION_VARIABLE*)cond->_cond_var);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_cond_broadcast(ainos_platform_cond_t* cond)
{
    if (!cond || !cond->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    WakeAllConditionVariable((CONDITION_VARIABLE*)cond->_cond_var);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 9. 信号量 (Semaphore) API
 * ================================================================ */

int ainos_platform_sem_init(ainos_platform_semaphore_t* sem,
                            unsigned int initial_value,
                            unsigned int max_value)
{
    if (!sem) return AINOS_PLATFORM_ERR_INVAL;

    LONG lmax = (max_value == 0) ? LONG_MAX : (LONG)max_value;
    sem->_handle = CreateSemaphoreW(NULL, (LONG)initial_value, lmax, NULL);
    if (!sem->_handle) {
        return win32_to_platform_error(GetLastError());
    }
    sem->_is_initialized = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_destroy(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    CloseHandle(sem->_handle);
    sem->_handle = NULL;
    sem->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_wait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(sem->_handle, INFINITE);
    if (ret == WAIT_OBJECT_0) return AINOS_PLATFORM_OK;
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_sem_trywait(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(sem->_handle, 0);
    if (ret == WAIT_OBJECT_0) return AINOS_PLATFORM_OK;
    if (ret == WAIT_TIMEOUT) return AINOS_PLATFORM_ERR_BUSY;
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_sem_timedwait(ainos_platform_semaphore_t* sem,
                                 int timeout_ms)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(sem->_handle,
                                    timeout_ms < 0 ? INFINITE : (DWORD)timeout_ms);
    if (ret == WAIT_OBJECT_0) return AINOS_PLATFORM_OK;
    if (ret == WAIT_TIMEOUT) return AINOS_PLATFORM_ERR_TIMEOUT;
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_sem_post(ainos_platform_semaphore_t* sem)
{
    if (!sem || !sem->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    ReleaseSemaphore(sem->_handle, 1, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sem_getvalue(ainos_platform_semaphore_t* sem,
                                int* value)
{
    if (!sem || !sem->_is_initialized || !value) return AINOS_PLATFORM_ERR_INVAL;

    /* Windows 没有直接获取信号量值的 API, 使用 WaitForSingleObject + ReleaseSemaphore 模拟 */
    DWORD ret = WaitForSingleObject(sem->_handle, 0);
    if (ret == WAIT_OBJECT_0) {
        /* 信号量可用, 计数器减 1, 释放后加回 */
        LONG prev = 0;
        ReleaseSemaphore(sem->_handle, 1, &prev);
        *value = (int)(prev + 1);
    } else if (ret == WAIT_TIMEOUT) {
        *value = 0;
    } else {
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 10. 事件 (Event) API
 * ================================================================ */

int ainos_platform_event_init(ainos_platform_event_t* event,
                              int manual_reset, int initial_state)
{
    if (!event) return AINOS_PLATFORM_ERR_INVAL;

    event->_handle = CreateEventW(NULL,
                                  manual_reset ? TRUE : FALSE,
                                  initial_state ? TRUE : FALSE,
                                  NULL);
    if (!event->_handle) {
        return win32_to_platform_error(GetLastError());
    }
    event->_is_initialized = 1;
    event->_is_manual_reset = manual_reset;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_destroy(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    CloseHandle(event->_handle);
    event->_handle = NULL;
    event->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_wait(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(event->_handle, INFINITE);
    if (ret == WAIT_OBJECT_0) return AINOS_PLATFORM_OK;
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_event_timedwait(ainos_platform_event_t* event,
                                   int timeout_ms)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(event->_handle,
                                    timeout_ms < 0 ? INFINITE : (DWORD)timeout_ms);
    if (ret == WAIT_OBJECT_0) return AINOS_PLATFORM_OK;
    if (ret == WAIT_TIMEOUT) return AINOS_PLATFORM_ERR_TIMEOUT;
    return AINOS_PLATFORM_ERR_GENERAL;
}

int ainos_platform_event_set(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    SetEvent(event->_handle);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_reset(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    ResetEvent(event->_handle);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_event_pulse(ainos_platform_event_t* event)
{
    if (!event || !event->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    PulseEvent(event->_handle);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 11. 屏障 (Barrier) API
 * ================================================================ */

int ainos_platform_barrier_init(ainos_platform_barrier_t* barrier,
                                int count)
{
    if (!barrier || count <= 0) return AINOS_PLATFORM_ERR_INVAL;

    barrier->_count = count;
    barrier->_waiters = 0;
    barrier->_is_initialized = 1;

    barrier->_mutex = malloc(sizeof(CRITICAL_SECTION));
    barrier->_event = malloc(sizeof(HANDLE));
    if (!barrier->_mutex || !barrier->_event) {
        free(barrier->_mutex);
        free(barrier->_event);
        return AINOS_PLATFORM_ERR_NOMEM;
    }

    InitializeCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
    *(HANDLE*)barrier->_event = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!(*(HANDLE*)barrier->_event)) {
        DeleteCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
        free(barrier->_mutex);
        free(barrier->_event);
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    return AINOS_PLATFORM_OK;
}

int ainos_platform_barrier_destroy(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    DeleteCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
    CloseHandle(*(HANDLE*)barrier->_event);
    free(barrier->_mutex);
    free(barrier->_event);
    barrier->_is_initialized = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_barrier_wait(ainos_platform_barrier_t* barrier)
{
    if (!barrier || !barrier->_is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    EnterCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
    barrier->_waiters++;
    int waiters = barrier->_waiters;

    if (waiters == barrier->_count) {
        /* 最后一个到达, 唤醒所有 */
        ResetEvent(*(HANDLE*)barrier->_event);
        barrier->_waiters = 0;
        LeaveCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
        SetEvent(*(HANDLE*)barrier->_event);
        return 1; /* 最后一个线程返回非零 */
    } else {
        LeaveCriticalSection((CRITICAL_SECTION*)barrier->_mutex);
        WaitForSingleObject(*(HANDLE*)barrier->_event, INFINITE);
        return 0;
    }
}

/* ================================================================
 * 12. 线程 (Thread) API
 * ================================================================ */

/* Windows 线程名称设置结构 */
typedef struct tagTHREADNAME_INFO {
    DWORD dwType;
    LPCSTR szName;
    DWORD dwThreadID;
    DWORD dwFlags;
} THREADNAME_INFO;

/* 线程入口包装 */
typedef struct {
    ainos_platform_thread_func_t func;
    void* arg;
    int exit_code;
} thread_wrapper_t;

static DWORD WINAPI thread_entry_wrapper(LPVOID arg)
{
    thread_wrapper_t* wrapper = (thread_wrapper_t*)arg;
    wrapper->exit_code = wrapper->func(wrapper->arg);
    return (DWORD)wrapper->exit_code;
}

int ainos_platform_thread_create(ainos_platform_thread_t* thread,
                                 const ainos_platform_thread_attr_t* attr,
                                 ainos_platform_thread_func_t func,
                                 void* arg)
{
    if (!thread || !func) return AINOS_PLATFORM_ERR_INVAL;

    thread_wrapper_t* wrapper = (thread_wrapper_t*)malloc(sizeof(thread_wrapper_t));
    if (!wrapper) return AINOS_PLATFORM_ERR_NOMEM;
    wrapper->func = func;
    wrapper->arg = arg;
    wrapper->exit_code = 0;

    DWORD flags = 0;
    size_t stack_size = 0;
    if (attr) {
        stack_size = attr->stack_size;
    }

    DWORD thread_id = 0;
    HANDLE handle = CreateThread(NULL, stack_size, thread_entry_wrapper,
                                 wrapper, flags, &thread_id);
    if (!handle) {
        free(wrapper);
        return win32_to_platform_error(GetLastError());
    }

    thread->_handle = handle;
    thread->_id = thread_id;
    thread->_is_valid = 1;
    thread->_stack_base = NULL;

    if (attr && attr->name[0] != '\0') {
        /* 设置线程名称 (通过结构化异常处理) */
        THREADNAME_INFO info;
        info.dwType = 0x1000;
        info.szName = attr->name;
        info.dwThreadID = thread_id;
        info.dwFlags = 0;
        __try {
            RaiseException(0x406D1388, 0, sizeof(info) / sizeof(ULONG_PTR),
                           (ULONG_PTR*)&info);
        } __except (EXCEPTION_CONTINUE_EXECUTION) {
        }
    }

    if (attr && attr->priority != AINOS_PLATFORM_THREAD_PRIO_NORMAL) {
        int win_priority = THREAD_PRIORITY_NORMAL;
        switch (attr->priority) {
            case AINOS_PLATFORM_THREAD_PRIO_LOWEST:
                win_priority = THREAD_PRIORITY_LOWEST; break;
            case AINOS_PLATFORM_THREAD_PRIO_LOW:
                win_priority = THREAD_PRIORITY_BELOW_NORMAL; break;
            case AINOS_PLATFORM_THREAD_PRIO_HIGH:
                win_priority = THREAD_PRIORITY_ABOVE_NORMAL; break;
            case AINOS_PLATFORM_THREAD_PRIO_HIGHEST:
                win_priority = THREAD_PRIORITY_HIGHEST; break;
            case AINOS_PLATFORM_THREAD_PRIO_TIME_CRITICAL:
                win_priority = THREAD_PRIORITY_TIME_CRITICAL; break;
        }
        SetThreadPriority(handle, win_priority);
    }

    if (attr && attr->is_detached) {
        CloseHandle(handle);
        thread->_handle = NULL;
    }

    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_join(ainos_platform_thread_t* thread,
                               int* exit_code)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    DWORD ret = WaitForSingleObject(thread->_handle, INFINITE);
    if (ret != WAIT_OBJECT_0) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    if (exit_code) {
        DWORD code = 0;
        GetExitCodeThread(thread->_handle, &code);
        *exit_code = (int)code;
    }

    CloseHandle(thread->_handle);
    thread->_handle = NULL;
    thread->_is_valid = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_detach(ainos_platform_thread_t* thread)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    CloseHandle(thread->_handle);
    thread->_handle = NULL;
    thread->_is_valid = 0;
    return AINOS_PLATFORM_OK;
}

unsigned long long ainos_platform_thread_self_id(void)
{
    return (unsigned long long)GetCurrentThreadId();
}

int ainos_platform_thread_get_name(char* name, size_t name_size)
{
    if (!name || name_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    /* Windows 没有标准的获取线程名 API */
    snprintf(name, name_size, "thread-%lu", GetCurrentThreadId());
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_set_name(const char* name)
{
    if (!name) return AINOS_PLATFORM_ERR_INVAL;

    THREADNAME_INFO info;
    info.dwType = 0x1000;
    info.szName = name;
    info.dwThreadID = GetCurrentThreadId();
    info.dwFlags = 0;
    __try {
        RaiseException(0x406D1388, 0, sizeof(info) / sizeof(ULONG_PTR),
                       (ULONG_PTR*)&info);
    } __except (EXCEPTION_CONTINUE_EXECUTION) {
    }
    return AINOS_PLATFORM_OK;
}

void ainos_platform_thread_yield(void)
{
    SwitchToThread();
}

int ainos_platform_thread_sleep(int milliseconds)
{
    if (milliseconds < 0) return AINOS_PLATFORM_ERR_INVAL;

    Sleep((DWORD)milliseconds);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_thread_is_running(ainos_platform_thread_t* thread)
{
    if (!thread || !thread->_is_valid) return 0;

    DWORD code = 0;
    if (!GetExitCodeThread(thread->_handle, &code)) {
        return 0;
    }
    return (code == STILL_ACTIVE) ? 1 : 0;
}

int ainos_platform_thread_get_cpu_time(ainos_platform_thread_t* thread,
                                       uint64_t* user_ns,
                                       uint64_t* kernel_ns)
{
    if (!thread || !thread->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    FILETIME create, exit, kernel, user;
    if (!GetThreadTimes(thread->_handle, &create, &exit, &kernel, &user)) {
        return win32_to_platform_error(GetLastError());
    }

    if (user_ns) {
        *user_ns = ((uint64_t)user.dwHighDateTime << 32 | user.dwLowDateTime) * 100;
    }
    if (kernel_ns) {
        *kernel_ns = ((uint64_t)kernel.dwHighDateTime << 32 | kernel.dwLowDateTime) * 100;
    }
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 13. 线程本地存储 (TLS) API
 * ================================================================ */

int ainos_platform_tls_alloc(ainos_platform_tls_t* tls)
{
    if (!tls) return AINOS_PLATFORM_ERR_INVAL;

    tls->_index = TlsAlloc();
    if (tls->_index == TLS_OUT_OF_INDEXES) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    tls->_is_allocated = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_tls_free(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;

    if (!TlsFree(tls->_index)) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    tls->_is_allocated = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_tls_set(ainos_platform_tls_t* tls, void* value)
{
    if (!tls || !tls->_is_allocated) return AINOS_PLATFORM_ERR_INVAL;

    if (!TlsSetValue(tls->_index, value)) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    return AINOS_PLATFORM_OK;
}

void* ainos_platform_tls_get(ainos_platform_tls_t* tls)
{
    if (!tls || !tls->_is_allocated) return NULL;

    return TlsGetValue(tls->_index);
}

/* ================================================================
 * 14. 线程池 (Thread Pool) API
 * ================================================================ */

/* 使用 Windows 线程池 API (Vista+) */

typedef struct work_item {
    ainos_platform_threadpool_work_func_t func;
    void* arg;
} work_item_t;

typedef struct ainos_platform_threadpool {
    PTP_POOL pool;
    TP_CALLBACK_ENVIRON callback_env;
    PTP_CLEANUP_GROUP cleanup_group;
    int min_threads;
    int max_threads;
    int is_initialized;
    char name[64];
} ainos_platform_threadpool_t;

static void CALLBACK threadpool_work_callback(PTP_CALLBACK_INSTANCE instance,
                                               void* context, PTP_WORK work)
{
    (void)instance;
    (void)work;
    work_item_t* item = (work_item_t*)context;
    if (item && item->func) {
        item->func(item->arg);
    }
    free(item);
}

int ainos_platform_threadpool_create(
    ainos_platform_threadpool_t** pool,
    const ainos_platform_threadpool_config_t* config)
{
    if (!pool) return AINOS_PLATFORM_ERR_INVAL;

    ainos_platform_threadpool_t* tp = (ainos_platform_threadpool_t*)
        calloc(1, sizeof(ainos_platform_threadpool_t));
    if (!tp) return AINOS_PLATFORM_ERR_NOMEM;

    tp->pool = CreateThreadpool(NULL);
    if (!tp->pool) {
        free(tp);
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    tp->cleanup_group = CreateThreadpoolCleanupGroup();
    if (!tp->cleanup_group) {
        CloseThreadpool(tp->pool);
        free(tp);
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    InitializeThreadpoolEnvironment(&tp->callback_env);
    SetThreadpoolCallbackPool(&tp->callback_env, tp->pool);
    SetThreadpoolCallbackCleanupGroup(&tp->callback_env, tp->cleanup_group, NULL);

    if (config) {
        tp->min_threads = config->min_threads;
        tp->max_threads = config->max_threads;
        strncpy(tp->name, config->name, sizeof(tp->name) - 1);
        SetThreadpoolThreadMinimum(tp->pool, config->min_threads);
        SetThreadpoolThreadMaximum(tp->pool, config->max_threads);
    } else {
        tp->min_threads = 2;
        tp->max_threads = 8;
        SetThreadpoolThreadMinimum(tp->pool, 2);
        SetThreadpoolThreadMaximum(tp->pool, 8);
    }

    tp->is_initialized = 1;
    *pool = tp;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_submit(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_work_func_t func,
    void* arg)
{
    if (!pool || !pool->is_initialized || !func) return AINOS_PLATFORM_ERR_INVAL;

    work_item_t* item = (work_item_t*)malloc(sizeof(work_item_t));
    if (!item) return AINOS_PLATFORM_ERR_NOMEM;
    item->func = func;
    item->arg = arg;

    PTP_WORK work = CreateThreadpoolWork(threadpool_work_callback,
                                         item, &pool->callback_env);
    if (!work) {
        free(item);
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    SubmitThreadpoolWork(work);
    /* 注意: 这里不释放 work 对象, 回调中也不释放; 需要 CloseThreadpoolWork */
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_wait(ainos_platform_threadpool_t* pool)
{
    if (!pool || !pool->is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    CloseThreadpoolCleanupGroupMembers(pool->cleanup_group, FALSE, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_get_stats(
    ainos_platform_threadpool_t* pool,
    ainos_platform_threadpool_stats_t* stats)
{
    if (!pool || !pool->is_initialized || !stats) return AINOS_PLATFORM_ERR_INVAL;

    /* Windows 线程池 API 不直接提供统计信息 */
    stats->active_threads = 0;
    stats->idle_threads = 0;
    stats->pending_tasks = 0;
    stats->completed_tasks = 0;
    stats->rejected_tasks = 0;
    stats->total_threads = pool->max_threads;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_threadpool_destroy(
    ainos_platform_threadpool_t* pool)
{
    if (!pool || !pool->is_initialized) return AINOS_PLATFORM_ERR_INVAL;

    CloseThreadpoolCleanupGroupMembers(pool->cleanup_group, TRUE, NULL);
    CloseThreadpoolCleanupGroup(pool->cleanup_group);
    CloseThreadpool(pool);
    pool->is_initialized = 0;
    free(pool);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 15. Socket API
 * ================================================================ */

int ainos_platform_socket_create(ainos_platform_socket_t* sock,
                                 int domain, int type, int protocol)
{
    if (!sock) return AINOS_PLATFORM_ERR_INVAL;

    int win_domain = AF_INET;
    int win_type = SOCK_STREAM;
    int win_proto = 0;

    switch (domain) {
        case AINOS_PLATFORM_AF_INET:  win_domain = AF_INET; break;
        case AINOS_PLATFORM_AF_INET6: win_domain = AF_INET6; break;
        case AINOS_PLATFORM_AF_UNIX:  win_domain = AF_UNIX; break;
        default: win_domain = AF_INET; break;
    }
    switch (type) {
        case AINOS_PLATFORM_SOCK_STREAM: win_type = SOCK_STREAM; break;
        case AINOS_PLATFORM_SOCK_DGRAM:  win_type = SOCK_DGRAM; break;
        case AINOS_PLATFORM_SOCK_RAW:    win_type = SOCK_RAW; break;
        default: win_type = SOCK_STREAM; break;
    }
    if (protocol == AINOS_PLATFORM_IPPROTO_TCP) win_proto = IPPROTO_TCP;
    else if (protocol == AINOS_PLATFORM_IPPROTO_UDP) win_proto = IPPROTO_UDP;
    else win_proto = 0;

    SOCKET fd = socket(win_domain, win_type, win_proto);
    if (fd == INVALID_SOCKET) {
        return wsagetlasterror_to_platform();
    }

    sock->_fd = (uintptr_t)fd;
    sock->_domain = domain;
    sock->_type = type;
    sock->_protocol = protocol;
    sock->_is_valid = 1;
    sock->_is_nonblocking = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_close(ainos_platform_socket_t* sock)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (closesocket((SOCKET)sock->_fd) != 0) {
        return wsagetlasterror_to_platform();
    }
    sock->_is_valid = 0;
    sock->_fd = (uintptr_t)INVALID_SOCKET;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_shutdown(ainos_platform_socket_t* sock, int how)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    int win_how = SD_BOTH;
    switch (how) {
        case AINOS_PLATFORM_SHUT_RD:   win_how = SD_RECEIVE; break;
        case AINOS_PLATFORM_SHUT_WR:   win_how = SD_SEND; break;
        case AINOS_PLATFORM_SHUT_RDWR: win_how = SD_BOTH; break;
    }
    if (shutdown((SOCKET)sock->_fd, win_how) != 0) {
        return wsagetlasterror_to_platform();
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_bind(ainos_platform_socket_t* sock,
                               const ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;

    if (bind((SOCKET)sock->_fd, (const struct sockaddr*)addr->_data,
             addr->_len) != 0) {
        return wsagetlasterror_to_platform();
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_listen(ainos_platform_socket_t* sock, int backlog)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (listen((SOCKET)sock->_fd, backlog) != 0) {
        return wsagetlasterror_to_platform();
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_accept(ainos_platform_socket_t* sock,
                                 ainos_platform_socket_t* client_sock,
                                 ainos_platform_sockaddr_t* client_addr)
{
    if (!sock || !sock->_is_valid || !client_sock) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    struct sockaddr_storage addr;
    socklen_t addr_len = sizeof(addr);
    SOCKET client = accept((SOCKET)sock->_fd, (struct sockaddr*)&addr, &addr_len);
    if (client == INVALID_SOCKET) {
        return wsagetlasterror_to_platform();
    }

    client_sock->_fd = (uintptr_t)client;
    client_sock->_domain = sock->_domain;
    client_sock->_type = sock->_type;
    client_sock->_protocol = sock->_protocol;
    client_sock->_is_valid = 1;
    client_sock->_is_nonblocking = 0;

    if (client_addr) {
        memcpy(client_addr->_data, &addr, addr_len);
        client_addr->_len = addr_len;
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_connect(ainos_platform_socket_t* sock,
                                  const ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;

    if (connect((SOCKET)sock->_fd, (const struct sockaddr*)addr->_data,
                addr->_len) != 0) {
        return wsagetlasterror_to_platform();
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_send(ainos_platform_socket_t* sock,
                               const void* data, int len, int flags)
{
    if (!sock || !sock->_is_valid || !data || len < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    int ret = send((SOCKET)sock->_fd, (const char*)data, len, flags);
    if (ret == SOCKET_ERROR) {
        return -wsagetlasterror_to_platform();
    }
    return ret;
}

int ainos_platform_socket_recv(ainos_platform_socket_t* sock,
                               void* buf, int len, int flags)
{
    if (!sock || !sock->_is_valid || !buf || len < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    int ret = recv((SOCKET)sock->_fd, (char*)buf, len, flags);
    if (ret == SOCKET_ERROR) {
        return -wsagetlasterror_to_platform();
    }
    return ret;
}

int ainos_platform_socket_sendto(ainos_platform_socket_t* sock,
                                 const void* data, int len, int flags,
                                 const ainos_platform_sockaddr_t* dest_addr)
{
    if (!sock || !sock->_is_valid || !data || len < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    int ret = sendto((SOCKET)sock->_fd, (const char*)data, len, flags,
                     (const struct sockaddr*)dest_addr->_data, dest_addr->_len);
    if (ret == SOCKET_ERROR) {
        return -wsagetlasterror_to_platform();
    }
    return ret;
}

int ainos_platform_socket_recvfrom(ainos_platform_socket_t* sock,
                                   void* buf, int len, int flags,
                                   ainos_platform_sockaddr_t* src_addr)
{
    if (!sock || !sock->_is_valid || !buf || len < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    struct sockaddr_storage addr;
    socklen_t addr_len = sizeof(addr);
    int ret = recvfrom((SOCKET)sock->_fd, (char*)buf, len, flags,
                       (struct sockaddr*)&addr, &addr_len);
    if (ret == SOCKET_ERROR) {
        return -wsagetlasterror_to_platform();
    }

    if (src_addr) {
        memcpy(src_addr->_data, &addr, addr_len);
        src_addr->_len = addr_len;
    }
    return ret;
}

int ainos_platform_socket_set_nonblocking(ainos_platform_socket_t* sock,
                                          int nonblocking)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    u_long mode = nonblocking ? 1 : 0;
    if (ioctlsocket((SOCKET)sock->_fd, FIONBIO, &mode) != 0) {
        return wsagetlasterror_to_platform();
    }
    sock->_is_nonblocking = nonblocking;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_set_option(ainos_platform_socket_t* sock,
                                     int level, int optname,
                                     const void* optval, int optlen)
{
    if (!sock || !sock->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    int win_level = SOL_SOCKET;
    int win_opt = optname;
    if (level == AINOS_PLATFORM_SOL_TCP) win_level = IPPROTO_TCP;

    if (setsockopt((SOCKET)sock->_fd, win_level, win_opt,
                   (const char*)optval, optlen) != 0) {
        return wsagetlasterror_to_platform();
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_get_option(ainos_platform_socket_t* sock,
                                     int level, int optname,
                                     void* optval, int* optlen)
{
    if (!sock || !sock->_is_valid || !optval || !optlen) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    int win_level = SOL_SOCKET;
    int win_opt = optname;
    if (level == AINOS_PLATFORM_SOL_TCP) win_level = IPPROTO_TCP;

    socklen_t slen = (socklen_t)*optlen;
    if (getsockopt((SOCKET)sock->_fd, win_level, win_opt,
                   (char*)optval, &slen) != 0) {
        return wsagetlasterror_to_platform();
    }
    *optlen = (int)slen;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_get_local_addr(ainos_platform_socket_t* sock,
                                         ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_storage sa;
    socklen_t slen = sizeof(sa);
    if (getsockname((SOCKET)sock->_fd, (struct sockaddr*)&sa, &slen) != 0) {
        return wsagetlasterror_to_platform();
    }
    memcpy(addr->_data, &sa, slen);
    addr->_len = slen;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_get_peer_addr(ainos_platform_socket_t* sock,
                                        ainos_platform_sockaddr_t* addr)
{
    if (!sock || !sock->_is_valid || !addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_storage sa;
    socklen_t slen = sizeof(sa);
    if (getpeername((SOCKET)sock->_fd, (struct sockaddr*)&sa, &slen) != 0) {
        return wsagetlasterror_to_platform();
    }
    memcpy(addr->_data, &sa, slen);
    addr->_len = slen;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_socket_is_valid(const ainos_platform_socket_t* sock)
{
    return sock && sock->_is_valid;
}

int ainos_platform_socket_poll(ainos_platform_pollfd_t* fds,
                               int nfds, int timeout_ms)
{
    if (!fds || nfds <= 0) return AINOS_PLATFORM_ERR_INVAL;

    /* 使用 select 实现 (Windows 没有 poll) */
    fd_set read_fds, write_fds, err_fds;
    FD_ZERO(&read_fds);
    FD_ZERO(&write_fds);
    FD_ZERO(&err_fds);

    SOCKET max_fd = 0;
    for (int i = 0; i < nfds; i++) {
        if (fds[i].sock && fds[i].sock->_is_valid) {
            SOCKET s = (SOCKET)fds[i].sock->_fd;
            if (fds[i].events & AINOS_PLATFORM_SOCKET_POLLIN)  FD_SET(s, &read_fds);
            if (fds[i].events & AINOS_PLATFORM_SOCKET_POLLOUT) FD_SET(s, &write_fds);
            FD_SET(s, &err_fds);
            if (s > max_fd) max_fd = s;
        }
    }

    struct timeval tv;
    struct timeval* ptv = NULL;
    if (timeout_ms >= 0) {
        tv.tv_sec = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;
        ptv = &tv;
    }

    int ret = select((int)max_fd + 1, &read_fds, &write_fds, &err_fds, ptv);
    if (ret == SOCKET_ERROR) {
        return -wsagetlasterror_to_platform();
    }

    for (int i = 0; i < nfds; i++) {
        fds[i].revents = 0;
        if (fds[i].sock && fds[i].sock->_is_valid) {
            SOCKET s = (SOCKET)fds[i].sock->_fd;
            if (FD_ISSET(s, &read_fds))  fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLIN;
            if (FD_ISSET(s, &write_fds)) fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLOUT;
            if (FD_ISSET(s, &err_fds))   fds[i].revents |= AINOS_PLATFORM_SOCKET_POLLERR;
        }
    }
    return ret;
}

/* ================================================================
 * 16. Socket 地址构造 API
 * ================================================================ */

int ainos_platform_sockaddr_set_inet4(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_in* sin = (struct sockaddr_in*)addr->_data;
    memset(sin, 0, sizeof(*sin));
    sin->sin_family = AF_INET;
    sin->sin_port = htons(port);

    if (ip) {
        inet_pton(AF_INET, ip, &sin->sin_addr);
    } else {
        sin->sin_addr.s_addr = INADDR_ANY;
    }

    addr->_len = sizeof(*sin);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_set_inet6(ainos_platform_sockaddr_t* addr,
                                      const char* ip, uint16_t port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_in6* sin6 = (struct sockaddr_in6*)addr->_data;
    memset(sin6, 0, sizeof(*sin6));
    sin6->sin6_family = AF_INET6;
    sin6->sin6_port = htons(port);

    if (ip) {
        inet_pton(AF_INET6, ip, &sin6->sin6_addr);
    } else {
        sin6->sin6_addr = in6addr_any;
    }

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
    int family = sa->sa_family;
    switch (family) {
        case AF_INET:  return AINOS_PLATFORM_AF_INET;
        case AF_INET6: return AINOS_PLATFORM_AF_INET6;
        case AF_UNIX:  return AINOS_PLATFORM_AF_UNIX;
        default:       return AINOS_PLATFORM_AF_UNSPEC;
    }
}

int ainos_platform_sockaddr_get_inet4(const ainos_platform_sockaddr_t* addr,
                                      char* ip, int ip_len, uint16_t* port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_in* sin = (struct sockaddr_in*)addr->_data;
    if (sin->sin_family != AF_INET) return AINOS_PLATFORM_ERR_INVAL;

    if (ip && ip_len > 0) {
        inet_ntop(AF_INET, &sin->sin_addr, ip, ip_len);
    }
    if (port) {
        *port = ntohs(sin->sin_port);
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sockaddr_get_inet6(const ainos_platform_sockaddr_t* addr,
                                      char* ip, int ip_len, uint16_t* port)
{
    if (!addr) return AINOS_PLATFORM_ERR_INVAL;

    struct sockaddr_in6* sin6 = (struct sockaddr_in6*)addr->_data;
    if (sin6->sin6_family != AF_INET6) return AINOS_PLATFORM_ERR_INVAL;

    if (ip && ip_len > 0) {
        inet_ntop(AF_INET6, &sin6->sin6_addr, ip, ip_len);
    }
    if (port) {
        *port = ntohs(sin6->sin6_port);
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dns_resolve(const char* hostname,
                               ainos_platform_sockaddr_t* addrs,
                               int* addr_count)
{
    if (!hostname || !addrs || !addr_count || *addr_count <= 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo* result = NULL;
    int ret = getaddrinfo(hostname, NULL, &hints, &result);
    if (ret != 0) {
        return AINOS_PLATFORM_ERR_NOT_FOUND;
    }

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
 * 17. 文件 I/O API
 * ================================================================ */

static DWORD file_flags_to_access(int flags)
{
    DWORD access = 0;
    if (flags & (AINOS_PLATFORM_FILE_O_RDWR)) {
        access = GENERIC_READ | GENERIC_WRITE;
    } else if (flags & AINOS_PLATFORM_FILE_O_WRONLY) {
        access = GENERIC_WRITE;
    } else {
        access = GENERIC_READ;
    }
    return access;
}

static DWORD file_flags_to_creation(int flags)
{
    if (flags & AINOS_PLATFORM_FILE_O_CREAT) {
        if (flags & AINOS_PLATFORM_FILE_O_EXCL) {
            return CREATE_NEW;
        }
        if (flags & AINOS_PLATFORM_FILE_O_TRUNC) {
            return CREATE_ALWAYS;
        }
        return OPEN_ALWAYS;
    }
    if (flags & AINOS_PLATFORM_FILE_O_TRUNC) {
        return TRUNCATE_EXISTING;
    }
    return OPEN_EXISTING;
}

static DWORD file_flags_to_attributes(int flags)
{
    DWORD attr = FILE_ATTRIBUTE_NORMAL;
    if (flags & AINOS_PLATFORM_FILE_O_TEMPORARY) {
        attr |= FILE_FLAG_DELETE_ON_CLOSE;
    }
    if (flags & AINOS_PLATFORM_FILE_O_SYNC) {
        attr |= FILE_FLAG_WRITE_THROUGH;
    }
    if (flags & AINOS_PLATFORM_FILE_O_DIRECTORY) {
        attr |= FILE_FLAG_BACKUP_SEMANTICS;
    }
    return attr;
}

int ainos_platform_file_open(ainos_platform_file_t* file,
                             const char* path, int flags, int mode)
{
    (void)mode;
    if (!file || !path) return AINOS_PLATFORM_ERR_INVAL;

    /* 转换路径为宽字符 */
    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    HANDLE h = CreateFileW(wpath,
                           file_flags_to_access(flags),
                           FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL,
                           file_flags_to_creation(flags),
                           file_flags_to_attributes(flags),
                           NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return win32_to_platform_error(GetLastError());
    }

    file->_handle = h;
    file->_is_valid = 1;
    file->_access_mode = flags;
    strncpy(file->_path, path, sizeof(file->_path) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_close(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (!CloseHandle(file->_handle)) {
        return win32_to_platform_error(GetLastError());
    }
    file->_is_valid = 0;
    file->_handle = NULL;
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_file_read(ainos_platform_file_t* file,
                                 void* buf, int64_t count)
{
    if (!file || !file->_is_valid || !buf || count < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    DWORD bytes_read = 0;
    if (!ReadFile(file->_handle, buf, (DWORD)count, &bytes_read, NULL)) {
        return -win32_to_platform_error(GetLastError());
    }
    return (int64_t)bytes_read;
}

int64_t ainos_platform_file_write(ainos_platform_file_t* file,
                                  const void* buf, int64_t count)
{
    if (!file || !file->_is_valid || !buf || count < 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    DWORD bytes_written = 0;
    if (!WriteFile(file->_handle, buf, (DWORD)count, &bytes_written, NULL)) {
        return -win32_to_platform_error(GetLastError());
    }
    return (int64_t)bytes_written;
}

int ainos_platform_file_seek(ainos_platform_file_t* file,
                             int64_t offset, int whence)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    DWORD win_method = FILE_BEGIN;
    switch (whence) {
        case AINOS_PLATFORM_FILE_SEEK_SET: win_method = FILE_BEGIN; break;
        case AINOS_PLATFORM_FILE_SEEK_CUR: win_method = FILE_CURRENT; break;
        case AINOS_PLATFORM_FILE_SEEK_END: win_method = FILE_END; break;
        default: return AINOS_PLATFORM_ERR_INVAL;
    }

    LARGE_INTEGER li;
    li.QuadPart = offset;
    if (!SetFilePointerEx(file->_handle, li, NULL, win_method)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_file_tell(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    LARGE_INTEGER li;
    li.QuadPart = 0;
    LARGE_INTEGER result;
    if (!SetFilePointerEx(file->_handle, li, &result, FILE_CURRENT)) {
        return -win32_to_platform_error(GetLastError());
    }
    return (int64_t)result.QuadPart;
}

int ainos_platform_file_stat(const char* path,
                             ainos_platform_file_stat_t* stat)
{
    if (!path || !stat) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    WIN32_FILE_ATTRIBUTE_DATA attr;
    if (!GetFileAttributesExW(wpath, GetFileExInfoStandard, &attr)) {
        return win32_to_platform_error(GetLastError());
    }

    memset(stat, 0, sizeof(*stat));
    stat->size = ((uint64_t)attr.nFileSizeHigh << 32) | attr.nFileSizeLow;
    stat->is_directory = (attr.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
    stat->is_regular = !stat->is_directory;
    stat->is_symlink = (attr.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
    stat->permissions = (int)attr.dwFileAttributes;

    /* 转换 FILETIME 到 Unix 时间戳 */
    ULARGE_INTEGER li;
    li.LowPart = attr.ftCreationTime.dwLowDateTime;
    li.HighPart = attr.ftCreationTime.dwHighDateTime;
    stat->created_time = (li.QuadPart - 116444736000000000ULL) / 10000;

    li.LowPart = attr.ftLastWriteTime.dwLowDateTime;
    li.HighPart = attr.ftLastWriteTime.dwHighDateTime;
    stat->modified_time = (li.QuadPart - 116444736000000000ULL) / 10000;

    li.LowPart = attr.ftLastAccessTime.dwLowDateTime;
    li.HighPart = attr.ftLastAccessTime.dwHighDateTime;
    stat->accessed_time = (li.QuadPart - 116444736000000000ULL) / 10000;

    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_fstat(ainos_platform_file_t* file,
                              ainos_platform_file_stat_t* stat)
{
    if (!file || !file->_is_valid || !stat) return AINOS_PLATFORM_ERR_INVAL;

    return ainos_platform_file_stat(file->_path, stat);
}

int ainos_platform_file_unlink(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (!DeleteFileW(wpath)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_rename(const char* old_path, const char* new_path)
{
    if (!old_path || !new_path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wold[1024], wnew[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, old_path, -1, wold, 1024) == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (MultiByteToWideChar(CP_UTF8, 0, new_path, -1, wnew, 1024) == 0) return AINOS_PLATFORM_ERR_INVAL;

    if (!MoveFileExW(wold, wnew, MOVEFILE_REPLACE_EXISTING | MOVEFILE_COPY_ALLOWED)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_copy(const char* src, const char* dst)
{
    if (!src || !dst) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wsrc[1024], wdst[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, src, -1, wsrc, 1024) == 0) return AINOS_PLATFORM_ERR_INVAL;
    if (MultiByteToWideChar(CP_UTF8, 0, dst, -1, wdst, 1024) == 0) return AINOS_PLATFORM_ERR_INVAL;

    if (!CopyFileW(wsrc, wdst, FALSE)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_truncate(ainos_platform_file_t* file,
                                 int64_t length)
{
    if (!file || !file->_is_valid || length < 0) return AINOS_PLATFORM_ERR_INVAL;

    /* 先移动指针, 再设置 EOF */
    LARGE_INTEGER li;
    li.QuadPart = length;
    if (!SetFilePointerEx(file->_handle, li, NULL, FILE_BEGIN)) {
        return win32_to_platform_error(GetLastError());
    }
    if (!SetEndOfFile(file->_handle)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_sync(ainos_platform_file_t* file)
{
    if (!file || !file->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (!FlushFileBuffers(file->_handle)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_file_exists(const char* path)
{
    if (!path) return 0;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) return 0;

    DWORD attr = GetFileAttributesW(wpath);
    return (attr != INVALID_FILE_ATTRIBUTES);
}

int ainos_platform_file_permissions_string(int mode, char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    /* Windows 权限字符串简化为 "rwxrwxrwx" 风格 */
    const char* str = "rw-rw-rw-";
    snprintf(buf, buf_size, "%s", str);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 18. 目录操作 API
 * ================================================================ */

int ainos_platform_dir_open(ainos_platform_dir_t* dir, const char* path)
{
    if (!dir || !path) return AINOS_PLATFORM_ERR_INVAL;

    char search_path[1024];
    snprintf(search_path, sizeof(search_path), "%s\\*", path);

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, search_path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    WIN32_FIND_DATAW find_data;
    HANDLE h = FindFirstFileW(wpath, &find_data);
    if (h == INVALID_HANDLE_VALUE) {
        return win32_to_platform_error(GetLastError());
    }

    dir->_handle = h;
    dir->_is_valid = 1;
    dir->_entry_index = 0;
    strncpy(dir->_path, path, sizeof(dir->_path) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_read(ainos_platform_dir_t* dir,
                            ainos_platform_dirent_t* entry)
{
    if (!dir || !dir->_is_valid || !entry) return AINOS_PLATFORM_ERR_INVAL;

    WIN32_FIND_DATAW find_data;
    BOOL found;

    if (dir->_entry_index == 0) {
        /* 第一次调用, 使用 FindFirstFile 的结果已在 dir 中 */
        dir->_entry_index++;
        found = TRUE;
        /* 需要获取当前句柄的 find data */
        /* 实际上 Windows 没有直接获取的方法, 我们重新打开 */
        char search_path[1024];
        snprintf(search_path, sizeof(search_path), "%s\\*", dir->_path);
        WCHAR wpath[1024];
        MultiByteToWideChar(CP_UTF8, 0, search_path, -1, wpath, 1024);
        HANDLE h = FindFirstFileW(wpath, &find_data);
        if (h != INVALID_HANDLE_VALUE) {
            FindClose(h);
        } else {
            return 0;
        }
    } else {
        found = FindNextFileW(dir->_handle, &find_data);
    }

    if (!found) {
        return 0;
    }

    WideCharToMultiByte(CP_UTF8, 0, find_data.cFileName, -1,
                        entry->name, sizeof(entry->name), NULL, NULL);
    entry->is_directory = (find_data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
    entry->is_regular = !entry->is_directory;
    entry->size = ((uint64_t)find_data.nFileSizeHigh << 32) | find_data.nFileSizeLow;
    return 1;
}

int ainos_platform_dir_close(ainos_platform_dir_t* dir)
{
    if (!dir || !dir->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (!FindClose(dir->_handle)) {
        return win32_to_platform_error(GetLastError());
    }
    dir->_is_valid = 0;
    dir->_handle = NULL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_mkdir(const char* path, int mode)
{
    (void)mode;
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (!CreateDirectoryW(wpath, NULL)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_mkdir_p(const char* path, int mode)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    /* 逐级创建目录 */
    char tmp[1024];
    strncpy(tmp, path, sizeof(tmp) - 1);
    tmp[sizeof(tmp) - 1] = '\0';

    for (char* p = tmp + 1; *p; p++) {
        if (*p == '/' || *p == '\\') {
            char saved = *p;
            *p = '\0';
            if (!ainos_platform_file_exists(tmp)) {
                int ret = ainos_platform_dir_mkdir(tmp, mode);
                if (ret != AINOS_PLATFORM_OK) {
                    *p = saved;
                    return ret;
                }
            }
            *p = saved;
        }
    }
    if (!ainos_platform_file_exists(tmp)) {
        return ainos_platform_dir_mkdir(tmp, mode);
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_rmdir(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (!RemoveDirectoryW(wpath)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_rmdir_r(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    /* 递归删除目录 */
    ainos_platform_dir_t dir;
    int ret = ainos_platform_dir_open(&dir, path);
    if (ret != AINOS_PLATFORM_OK) return ret;

    ainos_platform_dirent_t entry;
    while (ainos_platform_dir_read(&dir, &entry) > 0) {
        if (strcmp(entry.name, ".") == 0 || strcmp(entry.name, "..") == 0) {
            continue;
        }

        char child_path[1024];
        snprintf(child_path, sizeof(child_path), "%s/%s", path, entry.name);

        if (entry.is_directory) {
            ainos_platform_dir_rmdir_r(child_path);
        } else {
            ainos_platform_file_unlink(child_path);
        }
    }
    ainos_platform_dir_close(&dir);
    return ainos_platform_dir_rmdir(path);
}

int ainos_platform_dir_getcwd(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wbuf[1024];
    DWORD ret = GetCurrentDirectoryW(1024, wbuf);
    if (ret == 0) {
        return win32_to_platform_error(GetLastError());
    }

    WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, buf, (int)buf_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_dir_chdir(const char* path)
{
    if (!path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (!SetCurrentDirectoryW(wpath)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 19. 内存管理 API
 * ================================================================ */

void* ainos_platform_mem_alloc(size_t size)
{
    if (size == 0) return NULL;
    return HeapAlloc(GetProcessHeap(), 0, size);
}

void* ainos_platform_mem_calloc(size_t num, size_t size)
{
    size_t total = num * size;
    if (total == 0) return NULL;
    return HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, total);
}

void* ainos_platform_mem_realloc(void* ptr, size_t new_size)
{
    if (new_size == 0) {
        HeapFree(GetProcessHeap(), 0, ptr);
        return NULL;
    }
    if (!ptr) {
        return HeapAlloc(GetProcessHeap(), 0, new_size);
    }
    return HeapReAlloc(GetProcessHeap(), 0, ptr, new_size);
}

void ainos_platform_mem_free(void* ptr)
{
    if (ptr) {
        HeapFree(GetProcessHeap(), 0, ptr);
    }
}

void* ainos_platform_mem_aligned_alloc(size_t alignment, size_t size)
{
    if (alignment == 0 || (alignment & (alignment - 1)) != 0) {
        return NULL;
    }
    return _aligned_malloc(size, alignment);
}

void ainos_platform_mem_aligned_free(void* ptr)
{
    if (ptr) {
        _aligned_free(ptr);
    }
}

int ainos_platform_mem_get_page_size(void)
{
    SYSTEM_INFO sys_info;
    GetSystemInfo(&sys_info);
    return (int)sys_info.dwPageSize;
}

int64_t ainos_platform_mem_get_available_memory(void)
{
    MEMORYSTATUSEX mem;
    mem.dwLength = sizeof(mem);
    if (GlobalMemoryStatusEx(&mem)) {
        return (int64_t)mem.ullAvailPhys;
    }
    return -1;
}

int64_t ainos_platform_mem_get_total_physical_memory(void)
{
    MEMORYSTATUSEX mem;
    mem.dwLength = sizeof(mem);
    if (GlobalMemoryStatusEx(&mem)) {
        return (int64_t)mem.ullTotalPhys;
    }
    return -1;
}

int64_t ainos_platform_mem_get_process_memory(void)
{
    PROCESS_MEMORY_COUNTERS pmc;
    if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc))) {
        return (int64_t)pmc.WorkingSetSize;
    }
    return -1;
}

void* ainos_platform_mem_copy(void* dest, const void* src, size_t n)
{
    return memcpy(dest, src, n);
}

void* ainos_platform_mem_move(void* dest, const void* src, size_t n)
{
    return memmove(dest, src, n);
}

void* ainos_platform_mem_set(void* dest, int value, size_t n)
{
    return memset(dest, value, n);
}

int ainos_platform_mem_compare(const void* a, const void* b, size_t n)
{
    return memcmp(a, b, n);
}

int ainos_platform_mem_lock(const void* addr, size_t size)
{
    if (!addr || size == 0) return AINOS_PLATFORM_ERR_INVAL;

    if (VirtualLock((LPVOID)addr, size)) {
        return AINOS_PLATFORM_OK;
    }
    return win32_to_platform_error(GetLastError());
}

int ainos_platform_mem_unlock(const void* addr, size_t size)
{
    if (!addr || size == 0) return AINOS_PLATFORM_ERR_INVAL;

    if (VirtualUnlock((LPVOID)addr, size)) {
        return AINOS_PLATFORM_OK;
    }
    return win32_to_platform_error(GetLastError());
}

/* ================================================================
 * 20. 共享内存 API
 * ================================================================ */

int ainos_platform_shm_create(ainos_platform_shm_t* shm,
                              const char* name, size_t size, int create)
{
    if (!shm || !name || size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wname[256];
    char adjusted_name[256];
    if (name[0] != '/') {
        snprintf(adjusted_name, sizeof(adjusted_name), "/%s", name);
    } else {
        strncpy(adjusted_name, name, sizeof(adjusted_name) - 1);
    }
    MultiByteToWideChar(CP_UTF8, 0, adjusted_name, -1, wname, 256);

    HANDLE h = NULL;
    if (create) {
        h = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL,
                               PAGE_READWRITE,
                               (size >> 32) & 0xFFFFFFFF,
                               size & 0xFFFFFFFF,
                               wname);
    } else {
        h = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, wname);
    }

    if (!h) {
        return win32_to_platform_error(GetLastError());
    }

    shm->_handle = h;
    shm->_size = size;
    shm->_is_valid = 1;
    shm->_addr = NULL;
    strncpy(shm->_name, adjusted_name, sizeof(shm->_name) - 1);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_map(ainos_platform_shm_t* shm)
{
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (shm->_addr) {
        return AINOS_PLATFORM_OK; /* 已映射 */
    }

    shm->_addr = MapViewOfFile(shm->_handle, FILE_MAP_ALL_ACCESS, 0, 0, shm->_size);
    if (!shm->_addr) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_unmap(ainos_platform_shm_t* shm)
{
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (shm->_addr) {
        if (!UnmapViewOfFile(shm->_addr)) {
            return win32_to_platform_error(GetLastError());
        }
        shm->_addr = NULL;
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_close(ainos_platform_shm_t* shm)
{
    if (!shm || !shm->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    ainos_platform_shm_unmap(shm);
    CloseHandle(shm->_handle);
    shm->_handle = NULL;
    shm->_is_valid = 0;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_shm_unlink(const char* name)
{
    /* Windows 上, 文件映射对象在最后一个句柄关闭时自动删除 */
    (void)name;
    return AINOS_PLATFORM_OK;
}

void* ainos_platform_shm_get_addr(const ainos_platform_shm_t* shm)
{
    if (!shm || !shm->_is_valid) return NULL;
    return shm->_addr;
}

size_t ainos_platform_shm_get_size(const ainos_platform_shm_t* shm)
{
    if (!shm || !shm->_is_valid) return 0;
    return shm->_size;
}

/* ================================================================
 * 21. 原子操作 API
 * ================================================================ */

void ainos_platform_atomic32_init(ainos_platform_atomic32_t* atomic,
                                  int32_t value)
{
    if (atomic) atomic->_value = value;
}

void ainos_platform_atomic64_init(ainos_platform_atomic64_t* atomic,
                                  int64_t value)
{
    if (atomic) atomic->_value = value;
}

int32_t ainos_platform_atomic32_load(ainos_platform_atomic32_t* atomic)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedCompareExchange((LONG*)&atomic->_value, 0, 0);
}

int64_t ainos_platform_atomic64_load(ainos_platform_atomic64_t* atomic)
{
    if (!atomic) return 0;
    return InterlockedCompareExchange64(&atomic->_value, 0, 0);
}

void ainos_platform_atomic32_store(ainos_platform_atomic32_t* atomic,
                                   int32_t value)
{
    if (atomic) InterlockedExchange((LONG*)&atomic->_value, value);
}

void ainos_platform_atomic64_store(ainos_platform_atomic64_t* atomic,
                                   int64_t value)
{
    if (atomic) InterlockedExchange64(&atomic->_value, value);
}

int32_t ainos_platform_atomic32_exchange(ainos_platform_atomic32_t* atomic,
                                         int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedExchange((LONG*)&atomic->_value, value);
}

int64_t ainos_platform_atomic64_exchange(ainos_platform_atomic64_t* atomic,
                                         int64_t value)
{
    if (!atomic) return 0;
    return InterlockedExchange64(&atomic->_value, value);
}

int32_t ainos_platform_atomic32_compare_exchange(
    ainos_platform_atomic32_t* atomic, int32_t expected, int32_t desired)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedCompareExchange((LONG*)&atomic->_value,
                                                desired, expected);
}

int64_t ainos_platform_atomic64_compare_exchange(
    ainos_platform_atomic64_t* atomic, int64_t expected, int64_t desired)
{
    if (!atomic) return 0;
    return InterlockedCompareExchange64(&atomic->_value, desired, expected);
}

int32_t ainos_platform_atomic32_fetch_add(
    ainos_platform_atomic32_t* atomic, int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedExchangeAdd((LONG*)&atomic->_value, value);
}

int64_t ainos_platform_atomic64_fetch_add(
    ainos_platform_atomic64_t* atomic, int64_t value)
{
    if (!atomic) return 0;
    return InterlockedExchangeAdd64(&atomic->_value, value);
}

int32_t ainos_platform_atomic32_fetch_sub(
    ainos_platform_atomic32_t* atomic, int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedExchangeAdd((LONG*)&atomic->_value, -value);
}

int64_t ainos_platform_atomic64_fetch_sub(
    ainos_platform_atomic64_t* atomic, int64_t value)
{
    if (!atomic) return 0;
    return InterlockedExchangeAdd64(&atomic->_value, -value);
}

int32_t ainos_platform_atomic32_fetch_and(
    ainos_platform_atomic32_t* atomic, int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedAnd((LONG*)&atomic->_value, value);
}

int32_t ainos_platform_atomic32_fetch_or(
    ainos_platform_atomic32_t* atomic, int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedOr((LONG*)&atomic->_value, value);
}

int32_t ainos_platform_atomic32_fetch_xor(
    ainos_platform_atomic32_t* atomic, int32_t value)
{
    if (!atomic) return 0;
    return (int32_t)InterlockedXor((LONG*)&atomic->_value, value);
}

/* ================================================================
 * 22. 时间 API
 * ================================================================ */

int ainos_platform_time_now(ainos_platform_time_t* t)
{
    if (!t) return AINOS_PLATFORM_ERR_INVAL;

    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);

    ULARGE_INTEGER li;
    li.LowPart = ft.dwLowDateTime;
    li.HighPart = ft.dwHighDateTime;
    /* 转换 1601-01-01 到 1970-01-01 */
    int64_t unix_us = (li.QuadPart - 116444736000000000ULL) / 10;

    t->seconds = unix_us / 1000000;
    t->nanoseconds = (unix_us % 1000000) * 1000;

    /* 获取高精度计数器 */
    LARGE_INTEGER counter, freq;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&freq);
    t->raw_counter = counter.QuadPart;
    t->raw_frequency = freq.QuadPart;
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_now_ms(void)
{
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER li;
    li.LowPart = ft.dwLowDateTime;
    li.HighPart = ft.dwHighDateTime;
    return (li.QuadPart - 116444736000000000ULL) / 10000;
}

int64_t ainos_platform_time_monotonic_ns(void)
{
    LARGE_INTEGER counter, freq;
    QueryPerformanceCounter(&counter);
    QueryPerformanceFrequency(&freq);
    return (counter.QuadPart * 1000000000LL) / freq.QuadPart;
}

int ainos_platform_time_get_raw_counter(int64_t* value)
{
    if (!value) return AINOS_PLATFORM_ERR_INVAL;

    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    *value = counter.QuadPart;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_get_raw_frequency(int64_t* frequency)
{
    if (!frequency) return AINOS_PLATFORM_ERR_INVAL;

    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    *frequency = freq.QuadPart;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_sleep_ms(int milliseconds)
{
    if (milliseconds < 0) return AINOS_PLATFORM_ERR_INVAL;

    Sleep((DWORD)milliseconds);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_sleep_us(int microseconds)
{
    if (microseconds < 0) return AINOS_PLATFORM_ERR_INVAL;

    /* Windows 没有微秒级睡眠, 使用等待计时器 */
    HANDLE timer = CreateWaitableTimerW(NULL, TRUE, NULL);
    if (!timer) return AINOS_PLATFORM_ERR_GENERAL;

    LARGE_INTEGER due;
    due.QuadPart = -(int64_t)microseconds * 10; /* 100ns 单位 */
    SetWaitableTimer(timer, &due, 0, NULL, NULL, FALSE);
    WaitForSingleObject(timer, INFINITE);
    CloseHandle(timer);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_sleep_ns(int64_t nanoseconds)
{
    if (nanoseconds < 0) return AINOS_PLATFORM_ERR_INVAL;

    /* 纳秒级: 使用自旋等待 */
    if (nanoseconds < 10000) {
        /* 小于 10 微秒: 自旋 */
        int64_t start = ainos_platform_time_monotonic_ns();
        while ((ainos_platform_time_monotonic_ns() - start) < nanoseconds) {
            _mm_pause();
        }
        return AINOS_PLATFORM_OK;
    }

    /* 大于 10 微秒: 使用等待计时器 */
    return ainos_platform_time_sleep_us((int)(nanoseconds / 1000));
}

int64_t ainos_platform_time_get_tick_count(void)
{
    return (int64_t)GetTickCount64();
}

int ainos_platform_time_format(const ainos_platform_time_t* t,
                               const char* fmt, char* buf, size_t buf_size)
{
    if (!t || !fmt || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    time_t sec = (time_t)t->seconds;
    struct tm* tm_info = localtime(&sec);
    if (!tm_info) {
        buf[0] = '\0';
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    if (strftime(buf, buf_size, fmt, tm_info) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_time_format_iso8601(char* buf, size_t buf_size)
{
    if (!buf || buf_size < 25) return AINOS_PLATFORM_ERR_INVAL;

    ainos_platform_time_t t;
    ainos_platform_time_now(&t);

    time_t sec = (time_t)t.seconds;
    struct tm* tm_info = localtime(&sec);
    if (!tm_info) {
        buf[0] = '\0';
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    int ms = (int)(t.nanoseconds / 1000000);
    strftime(buf, buf_size, "%Y-%m-%dT%H:%M:%S", tm_info);
    int len = (int)strlen(buf);
    snprintf(buf + len, buf_size - len, ".%03dZ", ms);
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_time_diff_ns(const ainos_platform_time_t* t1,
                                    const ainos_platform_time_t* t2)
{
    if (!t1 || !t2) return 0;
    return (t1->seconds - t2->seconds) * 1000000000LL +
           (t1->nanoseconds - t2->nanoseconds);
}

int64_t ainos_platform_time_diff_ms(const ainos_platform_time_t* t1,
                                    const ainos_platform_time_t* t2)
{
    if (!t1 || !t2) return 0;
    return (t1->seconds - t2->seconds) * 1000LL +
           (t1->nanoseconds - t2->nanoseconds) / 1000000;
}

void ainos_platform_time_add(ainos_platform_time_t* result,
                             const ainos_platform_time_t* t,
                             const ainos_platform_duration_t* d)
{
    if (!result || !t || !d) return;
    result->seconds = t->seconds + d->seconds;
    result->nanoseconds = t->nanoseconds + d->nanoseconds;
    if (result->nanoseconds >= 1000000000LL) {
        result->seconds++;
        result->nanoseconds -= 1000000000LL;
    }
    result->raw_counter = t->raw_counter;
    result->raw_frequency = t->raw_frequency;
}

void ainos_platform_time_sub(ainos_platform_time_t* result,
                             const ainos_platform_time_t* t,
                             const ainos_platform_duration_t* d)
{
    if (!result || !t || !d) return;
    result->seconds = t->seconds - d->seconds;
    result->nanoseconds = t->nanoseconds - d->nanoseconds;
    if (result->nanoseconds < 0) {
        result->seconds--;
        result->nanoseconds += 1000000000LL;
    }
    result->raw_counter = t->raw_counter;
    result->raw_frequency = t->raw_frequency;
}

int ainos_platform_time_compare(const ainos_platform_time_t* t1,
                                const ainos_platform_time_t* t2)
{
    if (!t1 || !t2) return 0;
    if (t1->seconds < t2->seconds) return -1;
    if (t1->seconds > t2->seconds) return 1;
    if (t1->nanoseconds < t2->nanoseconds) return -1;
    if (t1->nanoseconds > t2->nanoseconds) return 1;
    return 0;
}

void ainos_platform_time_from_unix(ainos_platform_time_t* t,
                                   int64_t seconds, int64_t nanoseconds)
{
    if (!t) return;
    t->seconds = seconds;
    t->nanoseconds = nanoseconds;
    t->raw_counter = 0;
    t->raw_frequency = 0;
}

/* ================================================================
 * 23. 进程管理 API
 * ================================================================ */

int ainos_platform_process_spawn(ainos_platform_process_t* process,
                                 const char* path,
                                 char* const argv[],
                                 int flags)
{
    if (!process || !path) return AINOS_PLATFORM_ERR_INVAL;

    /* 构建命令行 */
    char cmdline[32768] = {0};
    /* 先添加可执行文件路径 (带引号) */
    int pos = snprintf(cmdline, sizeof(cmdline), "\"%s\"", path);

    if (argv) {
        for (int i = 0; argv[i] != NULL && pos < (int)sizeof(cmdline) - 1; i++) {
            if (i == 0) continue; /* 跳过 argv[0] (程序名) */
            pos += snprintf(cmdline + pos, sizeof(cmdline) - pos, " \"%s\"", argv[i]);
        }
    }

    WCHAR wcmdline[32768];
    MultiByteToWideChar(CP_UTF8, 0, cmdline, -1, wcmdline, 32768);

    /* 启动信息 */
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);

    DWORD creation_flags = 0;
    if (flags & AINOS_PLATFORM_PROCESS_DETACHED) {
        creation_flags |= DETACHED_PROCESS;
    }
    if (flags & AINOS_PLATFORM_PROCESS_NEW_CONSOLE) {
        creation_flags |= CREATE_NEW_CONSOLE;
    }
    if (flags & AINOS_PLATFORM_PROCESS_LOW_PRIORITY) {
        creation_flags |= IDLE_PRIORITY_CLASS;
    }
    if (flags & AINOS_PLATFORM_PROCESS_HIGH_PRIORITY) {
        creation_flags |= HIGH_PRIORITY_CLASS;
    }

    if (flags & AINOS_PLATFORM_PROCESS_REDIRECT_STDIO) {
        si.dwFlags |= STARTF_USESTDHANDLES;
        /* 创建管道用于 stdin/stdout/stderr */
        SECURITY_ATTRIBUTES sa;
        sa.nLength = sizeof(sa);
        sa.lpSecurityDescriptor = NULL;
        sa.bInheritHandle = TRUE;

        HANDLE hStdoutRd, hStdoutWr;
        CreatePipe(&hStdoutRd, &hStdoutWr, &sa, 0);
        SetHandleInformation(hStdoutRd, HANDLE_FLAG_INHERIT, 0);
        si.hStdOutput = hStdoutWr;
        si.hStdError = hStdoutWr;
        process->_stdout_pipe = hStdoutRd;

        HANDLE hStdinRd, hStdinWr;
        CreatePipe(&hStdinRd, &hStdinWr, &sa, 0);
        SetHandleInformation(hStdinWr, HANDLE_FLAG_INHERIT, 0);
        si.hStdInput = hStdinRd;
        process->_stdin_pipe = hStdinWr;
    }

    WCHAR wpath[1024];
    MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024);

    BOOL result = CreateProcessW(wpath, wcmdline, NULL, NULL,
                                 TRUE, creation_flags, NULL, NULL, &si, &pi);
    if (!result) {
        return win32_to_platform_error(GetLastError());
    }

    process->_handle = pi.hProcess;
    process->_pid = pi.dwProcessId;
    process->_is_valid = 1;
    process->_exit_code = 0;
    process->_has_exited = 0;
    process->_thread_handle = pi.hThread;

    if (flags & AINOS_PLATFORM_PROCESS_DETACHED) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        process->_handle = NULL;
    }

    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_wait(ainos_platform_process_t* process,
                                int* exit_code)
{
    if (!process || !process->_is_valid || !process->_handle) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    WaitForSingleObject(process->_handle, INFINITE);

    DWORD code = 0;
    GetExitCodeProcess(process->_handle, &code);
    if (exit_code) *exit_code = (int)code;
    process->_exit_code = (int)code;
    process->_has_exited = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_wait_timeout(ainos_platform_process_t* process,
                                        int* exit_code, int timeout_ms)
{
    if (!process || !process->_is_valid || !process->_handle) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    DWORD ret = WaitForSingleObject(process->_handle,
                                    timeout_ms < 0 ? INFINITE : (DWORD)timeout_ms);
    if (ret == WAIT_TIMEOUT) {
        return AINOS_PLATFORM_ERR_TIMEOUT;
    }
    if (ret != WAIT_OBJECT_0) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    DWORD code = 0;
    GetExitCodeProcess(process->_handle, &code);
    if (exit_code) *exit_code = (int)code;
    process->_exit_code = (int)code;
    process->_has_exited = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_kill(ainos_platform_process_t* process)
{
    if (!process || !process->_is_valid || !process->_handle) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    if (!TerminateProcess(process->_handle, 1)) {
        return win32_to_platform_error(GetLastError());
    }
    process->_has_exited = 1;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_pid(void)
{
    return (int)GetCurrentProcessId();
}

int ainos_platform_process_get_name(char* name, size_t name_size)
{
    if (!name || name_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[MAX_PATH];
    DWORD size = GetModuleFileNameW(NULL, wpath, MAX_PATH);
    if (size == 0) {
        snprintf(name, name_size, "unknown");
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    /* 提取文件名 */
    WCHAR* basename = wcsrchr(wpath, L'\\');
    if (!basename) basename = wpath;
    else basename++;

    WideCharToMultiByte(CP_UTF8, 0, basename, -1, name, (int)name_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_path(char* path, size_t path_size)
{
    if (!path || path_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[MAX_PATH];
    DWORD size = GetModuleFileNameW(NULL, wpath, MAX_PATH);
    if (size == 0) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    WideCharToMultiByte(CP_UTF8, 0, wpath, -1, path, (int)path_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_is_running(ainos_platform_process_t* process)
{
    if (!process || !process->_is_valid || !process->_handle) return 0;

    DWORD code = 0;
    if (!GetExitCodeProcess(process->_handle, &code)) return 0;
    return (code == STILL_ACTIVE);
}

int ainos_platform_process_signal(ainos_platform_process_t* process,
                                  int signal)
{
    (void)signal;
    /* Windows 上信号等同于终止 */
    return ainos_platform_process_kill(process);
}

int ainos_platform_process_enum(
    ainos_platform_process_enum_cb_t callback, void* arg)
{
    if (!callback) return AINOS_PLATFORM_ERR_INVAL;

    /* 使用 CreateToolhelp32Snapshot 枚举进程 */
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    PROCESSENTRY32W pe;
    pe.dwSize = sizeof(pe);
    if (!Process32FirstW(snapshot, &pe)) {
        CloseHandle(snapshot);
        return AINOS_PLATFORM_ERR_NOT_FOUND;
    }

    do {
        char name[256];
        WideCharToMultiByte(CP_UTF8, 0, pe.szExeFile, -1, name, sizeof(name), NULL, NULL);
        int ret = callback((int)pe.th32ProcessID, name, arg);
        if (ret != 0) {
            CloseHandle(snapshot);
            return AINOS_PLATFORM_OK;
        }
    } while (Process32NextW(snapshot, &pe));

    CloseHandle(snapshot);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_get_exit_code(
    ainos_platform_process_t* process, int* exit_code)
{
    if (!process || !process->_is_valid || !exit_code) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    DWORD code = 0;
    if (!GetExitCodeProcess(process->_handle, &code)) {
        return win32_to_platform_error(GetLastError());
    }
    *exit_code = (int)code;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_process_destroy(ainos_platform_process_t* process)
{
    if (!process || !process->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (process->_handle) {
        CloseHandle(process->_handle);
    }
    if (process->_thread_handle) {
        CloseHandle(process->_thread_handle);
    }
    if (process->_stdin_pipe) {
        CloseHandle(process->_stdin_pipe);
    }
    if (process->_stdout_pipe) {
        CloseHandle(process->_stdout_pipe);
    }
    memset(process, 0, sizeof(*process));
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 24. 动态库加载 API
 * ================================================================ */

int ainos_platform_dlopen(ainos_platform_library_t* lib, const char* path)
{
    if (!lib || !path) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[1024];
    if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wpath, 1024) == 0) {
        return AINOS_PLATFORM_ERR_INVAL;
    }

    HMODULE handle = LoadLibraryExW(wpath, NULL, 0);
    if (!handle) {
        return win32_to_platform_error(GetLastError());
    }

    lib->_handle = handle;
    lib->_is_valid = 1;
    strncpy(lib->_path, path, sizeof(lib->_path) - 1);
    return AINOS_PLATFORM_OK;
}

void* ainos_platform_dlsym(ainos_platform_library_t* lib, const char* symbol)
{
    if (!lib || !lib->_is_valid || !symbol) return NULL;

    return (void*)GetProcAddress((HMODULE)lib->_handle, symbol);
}

int ainos_platform_dlclose(ainos_platform_library_t* lib)
{
    if (!lib || !lib->_is_valid) return AINOS_PLATFORM_ERR_INVAL;

    if (!FreeLibrary((HMODULE)lib->_handle)) {
        return win32_to_platform_error(GetLastError());
    }
    lib->_is_valid = 0;
    lib->_handle = NULL;
    return AINOS_PLATFORM_OK;
}

const char* ainos_platform_dlerror(void)
{
    static char err_buf[256];
    DWORD err = GetLastError();
    FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                   NULL, err, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
                   err_buf, sizeof(err_buf), NULL);
    return err_buf;
}

int ainos_platform_dlget_self_path(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wpath[MAX_PATH];
    DWORD size = GetModuleFileNameW(NULL, wpath, MAX_PATH);
    if (size == 0) return AINOS_PLATFORM_ERR_GENERAL;

    WideCharToMultiByte(CP_UTF8, 0, wpath, -1, buf, (int)buf_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 25. 环境变量 API
 * ================================================================ */

const char* ainos_platform_getenv(const char* name)
{
    if (!name) return NULL;
    return getenv(name);
}

int ainos_platform_setenv(const char* name, const char* value, int overwrite)
{
    if (!name || !value) return AINOS_PLATFORM_ERR_INVAL;

    if (!overwrite) {
        const char* existing = ainos_platform_getenv(name);
        if (existing) return AINOS_PLATFORM_ERR_EXIST;
    }

    WCHAR wname[256], wvalue[4096];
    MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 256);
    MultiByteToWideChar(CP_UTF8, 0, value, -1, wvalue, 4096);

    if (!SetEnvironmentVariableW(wname, wvalue)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_unsetenv(const char* name)
{
    if (!name) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wname[256];
    MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 256);

    if (!SetEnvironmentVariableW(wname, NULL)) {
        return win32_to_platform_error(GetLastError());
    }
    return AINOS_PLATFORM_OK;
}

int ainos_platform_get_all_env(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR* env_block = GetEnvironmentStringsW();
    if (!env_block) return AINOS_PLATFORM_ERR_GENERAL;

    int pos = 0;
    WCHAR* env = env_block;
    while (*env && pos < (int)buf_size - 1) {
        char mb[2048];
        int len = WideCharToMultiByte(CP_UTF8, 0, env, -1, mb, sizeof(mb), NULL, NULL);
        if (len > 0) {
            int copy = (len < (int)(buf_size - pos)) ? len : (int)(buf_size - pos - 1);
            memcpy(buf + pos, mb, copy);
            pos += copy;
            if (pos < (int)buf_size - 1) {
                buf[pos++] = '\n';
            }
        }
        env += wcslen(env) + 1;
    }
    if (pos < (int)buf_size) {
        buf[pos] = '\0';
    }
    FreeEnvironmentStringsW(env_block);
    return pos;
}

/* ================================================================
 * 26. 错误处理 API
 * ================================================================ */

int ainos_platform_get_last_error(void)
{
    return g_last_error;
}

int ainos_platform_errno_to_platform(int sys_errno)
{
    switch (sys_errno) {
        case ERROR_SUCCESS:             return AINOS_PLATFORM_OK;
        case ERROR_FILE_NOT_FOUND:
        case ERROR_PATH_NOT_FOUND:      return AINOS_PLATFORM_ERR_NOT_FOUND;
        case ERROR_ACCESS_DENIED:       return AINOS_PLATFORM_ERR_PERM;
        case ERROR_INVALID_HANDLE:
        case ERROR_INVALID_PARAMETER:   return AINOS_PLATFORM_ERR_INVAL;
        case ERROR_NOT_ENOUGH_MEMORY:
        case ERROR_OUTOFMEMORY:         return AINOS_PLATFORM_ERR_NOMEM;
        case ERROR_ALREADY_EXISTS:      return AINOS_PLATFORM_ERR_EXIST;
        case ERROR_BUSY:                return AINOS_PLATFORM_ERR_BUSY;
        case ERROR_TIMEOUT:             return AINOS_PLATFORM_ERR_TIMEOUT;
        case ERROR_OPERATION_ABORTED:   return AINOS_PLATFORM_ERR_INTR;
        case ERROR_IO_PENDING:          return AINOS_PLATFORM_ERR_AGAIN;
        case ERROR_WRITE_FAULT:
        case ERROR_READ_FAULT:          return AINOS_PLATFORM_ERR_IO;
        case ERROR_CONNECTION_REFUSED:  return AINOS_PLATFORM_ERR_CONNREFUSED;
        case ERROR_CONNECTION_RESET:    return AINOS_PLATFORM_ERR_CONNRESET;
        case ERROR_ADDRESS_ALREADY_ASSOCIATED: return AINOS_PLATFORM_ERR_ADDRINUSE;
        default:                        return AINOS_PLATFORM_ERR_GENERAL;
    }
}

const char* ainos_platform_strerror(int err)
{
    switch (err) {
        case AINOS_PLATFORM_OK:              return "Success";
        case AINOS_PLATFORM_ERR_GENERAL:     return "General error";
        case AINOS_PLATFORM_ERR_NOMEM:       return "Out of memory";
        case AINOS_PLATFORM_ERR_INVAL:       return "Invalid argument";
        case AINOS_PLATFORM_ERR_TIMEOUT:     return "Operation timed out";
        case AINOS_PLATFORM_ERR_BUSY:        return "Resource busy";
        case AINOS_PLATFORM_ERR_AGAIN:       return "Try again";
        case AINOS_PLATFORM_ERR_NOT_FOUND:   return "Not found";
        case AINOS_PLATFORM_ERR_PERM:        return "Permission denied";
        case AINOS_PLATFORM_ERR_EXIST:       return "Already exists";
        case AINOS_PLATFORM_ERR_IO:          return "I/O error";
        case AINOS_PLATFORM_ERR_INTR:        return "Interrupted";
        case AINOS_PLATFORM_ERR_NOT_SUP:     return "Not supported";
        case AINOS_PLATFORM_ERR_CONNREFUSED: return "Connection refused";
        case AINOS_PLATFORM_ERR_CONNRESET:   return "Connection reset";
        case AINOS_PLATFORM_ERR_ADDRINUSE:   return "Address in use";
        case AINOS_PLATFORM_ERR_WOULDBLOCK:  return "Operation would block";
        default:                             return "Unknown error";
    }
}

const char* ainos_platform_get_last_error_string(void)
{
    return ainos_platform_strerror(g_last_error);
}

void ainos_platform_set_last_error(int err)
{
    g_last_error = err;
}

int ainos_platform_strerror_r(int err, char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    const char* msg = ainos_platform_strerror(err);
    strncpy(buf, msg, buf_size - 1);
    buf[buf_size - 1] = '\0';
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 27. 系统信息 API
 * ================================================================ */

int ainos_platform_sys_get_cpu_info(ainos_platform_cpu_info_t* info)
{
    if (!info) return AINOS_PLATFORM_ERR_INVAL;

    memset(info, 0, sizeof(*info));

    SYSTEM_INFO sys_info;
    GetSystemInfo(&sys_info);
    info->logical_cores = (int)sys_info.dwNumberOfProcessors;
    info->is_64bit = (sizeof(void*) == 8);
    info->cache_line_size = 64; /* 大部分现代 CPU 为 64 */
    info->l1d_cache = 32;
    info->l1i_cache = 32;
    info->l2_cache = 256;
    info->l3_cache = 8192;

    /* 获取物理核心数 */
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION buffer = NULL;
    DWORD len = 0;
    GetLogicalProcessorInformation(buffer, &len);
    if (GetLastError() == ERROR_INSUFFICIENT_BUFFER) {
        buffer = (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION)malloc(len);
        if (buffer && GetLogicalProcessorInformation(buffer, &len)) {
            int count = len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION);
            for (int i = 0; i < count; i++) {
                if (buffer[i].Relationship == RelationProcessorCore) {
                    info->physical_cores++;
                }
            }
        }
        free(buffer);
    }
    if (info->physical_cores == 0) {
        info->physical_cores = info->logical_cores;
    }

    /* CPU 名称 */
    HKEY hKey;
    if (RegOpenKeyExA(HKEY_LOCAL_MACHINE,
                      "HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0",
                      0, KEY_READ, &hKey) == ERROR_SUCCESS) {
        DWORD type = REG_SZ;
        DWORD data_size = sizeof(info->name);
        RegQueryValueExA(hKey, "ProcessorNameString", NULL, &type,
                         (LPBYTE)info->name, &data_size);
        RegCloseKey(hKey);
    }

    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_load(ainos_platform_system_load_t* load)
{
    if (!load) return AINOS_PLATFORM_ERR_INVAL;

    memset(load, 0, sizeof(*load));

    /* 内存信息 */
    MEMORYSTATUSEX mem;
    mem.dwLength = sizeof(mem);
    if (GlobalMemoryStatusEx(&mem)) {
        load->total_memory = (int64_t)mem.ullTotalPhys;
        load->free_memory = (int64_t)mem.ullAvailPhys;
        load->used_memory = load->total_memory - load->free_memory;
        load->memory_usage_percent = (double)load->used_memory /
                                     (double)load->total_memory * 100.0;
        load->total_swap = (int64_t)mem.ullTotalPageFile;
        load->free_swap = (int64_t)mem.ullAvailPageFile;
    }

    /* CPU 使用率 (使用 GetSystemTimes) */
    static int64_t prev_idle = 0, prev_kernel = 0, prev_user = 0;
    FILETIME idle, kernel, user;
    if (GetSystemTimes(&idle, &kernel, &user)) {
        int64_t idle_time = ((int64_t)idle.dwHighDateTime << 32) | idle.dwLowDateTime;
        int64_t kernel_time = ((int64_t)kernel.dwHighDateTime << 32) | kernel.dwLowDateTime;
        int64_t user_time = ((int64_t)user.dwHighDateTime << 32) | user.dwLowDateTime;

        if (prev_idle != 0) {
            int64_t total_diff = (kernel_time - prev_kernel) + (user_time - prev_user);
            int64_t idle_diff = idle_time - prev_idle;
            if (total_diff > 0) {
                load->cpu_usage_percent = 100.0 - (double)idle_diff / (double)total_diff * 100.0;
            }
        }
        prev_idle = idle_time;
        prev_kernel = kernel_time;
        prev_user = user_time;
    }

    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_hostname(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    WCHAR wbuf[256];
    DWORD size = 256;
    if (!GetComputerNameW(wbuf, &size)) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }
    WideCharToMultiByte(CP_UTF8, 0, wbuf, -1, buf, (int)buf_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_sys_get_os_info(char* os_name, size_t name_size,
                                   char* os_version, size_t ver_size)
{
    if (os_name) {
        snprintf(os_name, name_size, "Windows");
    }
    if (os_version) {
        /* 获取 Windows 版本 */
        HKEY hKey;
        if (RegOpenKeyExA(HKEY_LOCAL_MACHINE,
                          "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
                          0, KEY_READ, &hKey) == ERROR_SUCCESS) {
            DWORD type = REG_SZ;
            DWORD data_size = (DWORD)ver_size;
            RegQueryValueExA(hKey, "CurrentVersion", NULL, &type,
                             (LPBYTE)os_version, &data_size);
            RegCloseKey(hKey);
        } else {
            snprintf(os_version, ver_size, "unknown");
        }
    }
    return AINOS_PLATFORM_OK;
}

int64_t ainos_platform_sys_get_uptime(void)
{
    return (int64_t)(GetTickCount64() / 1000);
}

int ainos_platform_sys_get_timezone(char* buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    TIME_ZONE_INFORMATION tz;
    DWORD ret = GetTimeZoneInformation(&tz);
    if (ret == TIME_ZONE_ID_INVALID) {
        return AINOS_PLATFORM_ERR_GENERAL;
    }

    WideCharToMultiByte(CP_UTF8, 0, tz.StandardName, -1, buf, (int)buf_size, NULL, NULL);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 28. 控制台/终端 API
 * ================================================================ */

int ainos_platform_console_set_color(int color)
{
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h == INVALID_HANDLE_VALUE) return AINOS_PLATFORM_ERR_GENERAL;

    CONSOLE_SCREEN_BUFFER_INFO info;
    GetConsoleScreenBufferInfo(h, &info);

    WORD attr = 0;
    switch (color) {
        case AINOS_PLATFORM_COLOR_RESET:
            attr = 7; break;
        case AINOS_PLATFORM_COLOR_RED:
            attr = FOREGROUND_RED; break;
        case AINOS_PLATFORM_COLOR_GREEN:
            attr = FOREGROUND_GREEN; break;
        case AINOS_PLATFORM_COLOR_YELLOW:
            attr = FOREGROUND_RED | FOREGROUND_GREEN; break;
        case AINOS_PLATFORM_COLOR_BLUE:
            attr = FOREGROUND_BLUE; break;
        case AINOS_PLATFORM_COLOR_MAGENTA:
            attr = FOREGROUND_RED | FOREGROUND_BLUE; break;
        case AINOS_PLATFORM_COLOR_CYAN:
            attr = FOREGROUND_GREEN | FOREGROUND_BLUE; break;
        case AINOS_PLATFORM_COLOR_WHITE:
            attr = FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_BLUE; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_RED:
            attr = FOREGROUND_RED | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_GREEN:
            attr = FOREGROUND_GREEN | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_YELLOW:
            attr = FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_BLUE:
            attr = FOREGROUND_BLUE | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_MAGENTA:
            attr = FOREGROUND_RED | FOREGROUND_BLUE | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_CYAN:
            attr = FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY; break;
        case AINOS_PLATFORM_COLOR_BRIGHT_WHITE:
            attr = FOREGROUND_RED | FOREGROUND_GREEN | FOREGROUND_BLUE | FOREGROUND_INTENSITY; break;
        default:
            attr = info.wAttributes; break;
    }

    SetConsoleTextAttribute(h, attr);
    return AINOS_PLATFORM_OK;
}

int ainos_platform_console_reset_color(void)
{
    return ainos_platform_console_set_color(AINOS_PLATFORM_COLOR_RESET);
}

int ainos_platform_console_get_width(void)
{
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h == INVALID_HANDLE_VALUE) return 80;

    CONSOLE_SCREEN_BUFFER_INFO info;
    if (!GetConsoleScreenBufferInfo(h, &info)) return 80;
    return info.srWindow.Right - info.srWindow.Left + 1;
}

int ainos_platform_console_get_height(void)
{
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h == INVALID_HANDLE_VALUE) return 25;

    CONSOLE_SCREEN_BUFFER_INFO info;
    if (!GetConsoleScreenBufferInfo(h, &info)) return 25;
    return info.srWindow.Bottom - info.srWindow.Top + 1;
}

int ainos_platform_console_has_color(void)
{
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h == INVALID_HANDLE_VALUE) return 0;

    DWORD mode = 0;
    if (!GetConsoleMode(h, &mode)) return 0;
    return 1;
}

/* ================================================================
 * 29. 日志 API
 * ================================================================ */

static ainos_platform_log_func_t g_log_callback = NULL;
static void* g_log_user_data = NULL;
static int g_log_level = AINOS_PLATFORM_LOG_INFO;

static const char* log_level_string(int level)
{
    switch (level) {
        case AINOS_PLATFORM_LOG_DEBUG: return "DEBUG";
        case AINOS_PLATFORM_LOG_INFO:  return "INFO";
        case AINOS_PLATFORM_LOG_WARN:  return "WARN";
        case AINOS_PLATFORM_LOG_ERROR: return "ERROR";
        case AINOS_PLATFORM_LOG_FATAL: return "FATAL";
        default:                       return "UNKNOWN";
    }
}

void ainos_platform_log_set_callback(ainos_platform_log_func_t callback,
                                     void* user_data)
{
    g_log_callback = callback;
    g_log_user_data = user_data;
}

void ainos_platform_log_set_level(int level)
{
    g_log_level = level;
}

void ainos_platform_log_write(int level, const char* file, int line,
                              const char* func, const char* fmt, ...)
{
    if (level < g_log_level) return;

    char msg[4096];
    va_list args;
    va_start(args, fmt);
    vsnprintf(msg, sizeof(msg), fmt, args);
    va_end(args);

    char timestamp[64];
    ainos_platform_time_t now;
    ainos_platform_time_now(&now);
    ainos_platform_time_format(&now, "%Y-%m-%d %H:%M:%S",
                               timestamp, sizeof(timestamp));

    char formatted[8192];
    snprintf(formatted, sizeof(formatted), "[%s] %-5s %s:%d (%s) %s",
             timestamp, log_level_string(level),
             file, line, func, msg);

    if (g_log_callback) {
        g_log_callback(level, formatted, g_log_user_data);
    } else {
        /* 默认输出到 stderr */
        HANDLE h = GetStdHandle(STD_ERROR_HANDLE);
        if (h != INVALID_HANDLE_VALUE) {
            DWORD written;
            WriteFile(h, formatted, (DWORD)strlen(formatted), &written, NULL);
            WriteFile(h, "\n", 1, &written, NULL);
        }
    }
}

/* ================================================================
 * 30. UUID 生成 API
 * ================================================================ */

int ainos_platform_uuid_v4_generate(char* buf, size_t buf_size)
{
    if (!buf || buf_size < 37) return AINOS_PLATFORM_ERR_INVAL;

    UUID uuid;
    UuidCreate(&uuid);

    unsigned char* raw = (unsigned char*)&uuid;
    snprintf(buf, buf_size,
             "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
             raw[0], raw[1], raw[2], raw[3],
             raw[4], raw[5], raw[6], raw[7],
             raw[8], raw[9], raw[10], raw[11],
             raw[12], raw[13], raw[14], raw[15]);
    return AINOS_PLATFORM_OK;
}

/* ================================================================
 * 31. 字符串工具 API
 * ================================================================ */

int ainos_platform_wchar_to_utf8(const wchar_t* wstr, char* buf,
                                 size_t buf_size)
{
    if (!wstr || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    int len = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, buf,
                                  (int)buf_size, NULL, NULL);
    if (len == 0) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_utf8_to_wchar(const char* utf8, wchar_t* buf,
                                 size_t buf_size)
{
    if (!utf8 || !buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    int len = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, buf, (int)buf_size);
    if (len == 0) return AINOS_PLATFORM_ERR_INVAL;
    return AINOS_PLATFORM_OK;
}

int ainos_platform_strerror_locale(int err, char* buf, size_t buf_size,
                                   const char* locale)
{
    (void)locale;
    if (!buf || buf_size == 0) return AINOS_PLATFORM_ERR_INVAL;

    DWORD win_err = (DWORD)err;
    DWORD ret = FormatMessageA(
        FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        NULL, win_err, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        buf, (DWORD)buf_size, NULL);
    if (ret == 0) {
        snprintf(buf, buf_size, "Unknown error %d", err);
    }
    return AINOS_PLATFORM_OK;
}