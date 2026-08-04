// Ainos OS - Platform Abstraction Layer (PAL) Unit Tests
// 跨平台单元测试: 验证所有平台抽象 API 的正确性
//
// Copyright (c) 2024 AinosOS
// SPDX-License-Identifier: MIT
//
// 编译:
//   gcc -o test_platform test_platform.c -l ainos-platform -lpthread
// 运行:
//   ./test_platform              # 运行所有测试
//   ./test_platform --mutex      # 仅运行 mutex 测试
//   ./test_platform --thread     # 仅运行 thread 测试
//   ./test_platform --list       # 列出所有测试

#include "ainos/platform.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/* ================================================================
 * 测试框架
 * ================================================================ */

static int g_tests_passed = 0;
static int g_tests_failed = 0;
static int g_assertions_passed = 0;
static int g_assertions_failed = 0;

#define TEST_ASSERT(cond, msg) do { \
    if (!(cond)) { \
        g_assertions_failed++; \
        printf("  FAIL: %s (%s:%d)\n", msg, __FILE__, __LINE__); \
        return -1; \
    } else { \
        g_assertions_passed++; \
    } \
} while (0)

#define TEST_ASSERT_EQ(a, b, msg) TEST_ASSERT((a) == (b), msg)
#define TEST_ASSERT_NE(a, b, msg) TEST_ASSERT((a) != (b), msg)
#define TEST_ASSERT_OK(ret, msg) TEST_ASSERT((ret) >= 0, msg)
#define TEST_ASSERT_ERR(ret, msg) TEST_ASSERT((ret) < 0, msg)

#define RUN_TEST(name) do { \
    printf("  Test: %-50s ", name); \
    if (test_##name() == 0) { \
        printf("[PASS]\n"); \
        g_tests_passed++; \
    } else { \
        printf("[FAIL]\n"); \
        g_tests_failed++; \
    } \
} while (0)

/* ================================================================
 * Mutex 测试
 * ================================================================ */

static int test_mutex_init_destroy(void)
{
    ainos_platform_mutex_t mutex;
    memset(&mutex, 0, sizeof(mutex));

    int ret = ainos_platform_mutex_init(&mutex, AINOS_PLATFORM_MUTEX_NORMAL);
    TEST_ASSERT_OK(ret, "mutex_init normal");
    TEST_ASSERT(ainos_platform_mutex_is_valid(&mutex), "mutex_is_valid");

    ret = ainos_platform_mutex_destroy(&mutex);
    TEST_ASSERT_OK(ret, "mutex_destroy");
    TEST_ASSERT(!ainos_platform_mutex_is_valid(&mutex), "mutex_is_valid after destroy");
    return 0;
}

static int test_mutex_lock_unlock(void)
{
    ainos_platform_mutex_t mutex;
    ainos_platform_mutex_init(&mutex, AINOS_PLATFORM_MUTEX_NORMAL);

    int ret = ainos_platform_mutex_lock(&mutex);
    TEST_ASSERT_OK(ret, "mutex_lock");

    ret = ainos_platform_mutex_unlock(&mutex);
    TEST_ASSERT_OK(ret, "mutex_unlock");

    ainos_platform_mutex_destroy(&mutex);
    return 0;
}

static int test_mutex_trylock(void)
{
    ainos_platform_mutex_t mutex;
    ainos_platform_mutex_init(&mutex, AINOS_PLATFORM_MUTEX_NORMAL);

    int ret = ainos_platform_mutex_trylock(&mutex);
    TEST_ASSERT_OK(ret, "mutex_trylock (unlocked)");

    ret = ainos_platform_mutex_trylock(&mutex);
    if (ret == AINOS_PLATFORM_ERR_BUSY) {
        /* 非递归互斥锁应返回 BUSY */
    }

    ainos_platform_mutex_unlock(&mutex);
    ainos_platform_mutex_destroy(&mutex);
    return 0;
}

static int test_mutex_recursive(void)
{
    ainos_platform_mutex_t mutex;
    ainos_platform_mutex_init(&mutex, AINOS_PLATFORM_MUTEX_RECURSIVE);

    int ret = ainos_platform_mutex_lock(&mutex);
    TEST_ASSERT_OK(ret, "recursive mutex_lock (1)");

    ret = ainos_platform_mutex_lock(&mutex);
    TEST_ASSERT_OK(ret, "recursive mutex_lock (2)");

    ainos_platform_mutex_unlock(&mutex);
    ainos_platform_mutex_unlock(&mutex);
    ainos_platform_mutex_destroy(&mutex);
    return 0;
}

static int test_mutex_invalid(void)
{
    int ret = ainos_platform_mutex_lock(NULL);
    TEST_ASSERT_ERR(ret, "mutex_lock(NULL)");
    TEST_ASSERT(!ainos_platform_mutex_is_valid(NULL), "mutex_is_valid(NULL)");
    return 0;
}

/* 互斥锁竞争测试 */
static ainos_platform_mutex_t g_contention_mutex;
static int g_contention_counter = 0;
static int g_contention_iterations = 10000;

static int contention_worker(void* arg)
{
    (void)arg;
    for (int i = 0; i < g_contention_iterations; i++) {
        ainos_platform_mutex_lock(&g_contention_mutex);
        g_contention_counter++;
        ainos_platform_mutex_unlock(&g_contention_mutex);
    }
    return 0;
}

static int test_mutex_contention(void)
{
    ainos_platform_mutex_init(&g_contention_mutex, AINOS_PLATFORM_MUTEX_NORMAL);
    g_contention_counter = 0;

    ainos_platform_thread_t t1, t2;
    ainos_platform_thread_create(&t1, NULL, contention_worker, NULL);
    ainos_platform_thread_create(&t2, NULL, contention_worker, NULL);
    ainos_platform_thread_join(&t1, NULL);
    ainos_platform_thread_join(&t2, NULL);

    TEST_ASSERT_EQ(g_contention_counter, g_contention_iterations * 2,
                   "contention counter");
    ainos_platform_mutex_destroy(&g_contention_mutex);
    return 0;
}

/* ================================================================
 * Thread 测试
 * ================================================================ */

static int thread_test_value = 0;
static int thread_worker(void* arg)
{
    thread_test_value = *(int*)arg;
    return thread_test_value * 2;
}

static int test_thread_create_join(void)
{
    int arg = 42;
    ainos_platform_thread_t thread;
    int ret = ainos_platform_thread_create(&thread, NULL, thread_worker, &arg);
    TEST_ASSERT_OK(ret, "thread_create");

    int exit_code = 0;
    ret = ainos_platform_thread_join(&thread, &exit_code);
    TEST_ASSERT_OK(ret, "thread_join");
    TEST_ASSERT_EQ(exit_code, 84, "thread exit code");
    return 0;
}

static int test_thread_self_id(void)
{
    unsigned long long id = ainos_platform_thread_self_id();
    TEST_ASSERT_NE(id, 0ULL, "thread_self_id non-zero");
    return 0;
}

static int test_thread_sleep(void)
{
    int64_t start = ainos_platform_time_now_ms();
    ainos_platform_thread_sleep(50);
    int64_t elapsed = ainos_platform_time_now_ms() - start;
    TEST_ASSERT(elapsed >= 40, "thread_sleep >= 40ms");
    return 0;
}

static int test_thread_name(void)
{
    int ret = ainos_platform_thread_set_name("test-thread");
    TEST_ASSERT_OK(ret, "thread_set_name");

    char name[64] = {0};
    ret = ainos_platform_thread_get_name(name, sizeof(name));
    TEST_ASSERT_OK(ret, "thread_get_name");
    /* 名称可能被截断或包含线程 ID, 只检查非空 */
    TEST_ASSERT(strlen(name) > 0, "thread_name non-empty");
    return 0;
}

/* ================================================================
 * RWLock 测试
 * ================================================================ */

static int test_rwlock_read_write(void)
{
    ainos_platform_rwlock_t rwlock;
    int ret = ainos_platform_rwlock_init(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_init");

    ret = ainos_platform_rwlock_rdlock(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_rdlock");

    ret = ainos_platform_rwlock_unlock(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_unlock (read)");

    ret = ainos_platform_rwlock_wrlock(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_wrlock");

    ret = ainos_platform_rwlock_unlock(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_unlock (write)");

    ret = ainos_platform_rwlock_destroy(&rwlock);
    TEST_ASSERT_OK(ret, "rwlock_destroy");
    return 0;
}

/* ================================================================
 * 条件变量测试
 * ================================================================ */

static ainos_platform_mutex_t g_cond_mutex;
static ainos_platform_cond_t g_cond;
static int g_cond_signaled = 0;

static int cond_waiter(void* arg)
{
    (void)arg;
    ainos_platform_mutex_lock(&g_cond_mutex);
    while (!g_cond_signaled) {
        ainos_platform_cond_wait(&g_cond, &g_cond_mutex);
    }
    ainos_platform_mutex_unlock(&g_cond_mutex);
    return 0;
}

static int test_cond_signal_wait(void)
{
    ainos_platform_mutex_init(&g_cond_mutex, AINOS_PLATFORM_MUTEX_NORMAL);
    ainos_platform_cond_init(&g_cond);
    g_cond_signaled = 0;

    ainos_platform_thread_t thread;
    ainos_platform_thread_create(&thread, NULL, cond_waiter, NULL);

    ainos_platform_thread_sleep(50);
    ainos_platform_mutex_lock(&g_cond_mutex);
    g_cond_signaled = 1;
    ainos_platform_cond_signal(&g_cond);
    ainos_platform_mutex_unlock(&g_cond_mutex);

    ainos_platform_thread_join(&thread, NULL);
    ainos_platform_cond_destroy(&g_cond);
    ainos_platform_mutex_destroy(&g_cond_mutex);
    return 0;
}

/* ================================================================
 * 信号量测试
 * ================================================================ */

static int test_semaphore_init_wait_post(void)
{
    ainos_platform_semaphore_t sem;
    int ret = ainos_platform_sem_init(&sem, 0, 10);
    TEST_ASSERT_OK(ret, "sem_init");

    int value = -1;
    ret = ainos_platform_sem_getvalue(&sem, &value);
    TEST_ASSERT_OK(ret, "sem_getvalue");
    TEST_ASSERT_EQ(value, 0, "sem initial value");

    ret = ainos_platform_sem_post(&sem);
    TEST_ASSERT_OK(ret, "sem_post");

    ret = ainos_platform_sem_getvalue(&sem, &value);
    TEST_ASSERT_EQ(value, 1, "sem value after post");

    ret = ainos_platform_sem_wait(&sem);
    TEST_ASSERT_OK(ret, "sem_wait");

    ret = ainos_platform_sem_trywait(&sem);
    TEST_ASSERT_EQ(ret, AINOS_PLATFORM_ERR_BUSY, "sem_trywait (empty)");

    ainos_platform_sem_destroy(&sem);
    return 0;
}

/* ================================================================
 * 事件测试
 * ================================================================ */

static int test_event_manual_reset(void)
{
    ainos_platform_event_t event;
    int ret = ainos_platform_event_init(&event, 1, 0);
    TEST_ASSERT_OK(ret, "event_init manual");

    ret = ainos_platform_event_set(&event);
    TEST_ASSERT_OK(ret, "event_set");

    ret = ainos_platform_event_wait(&event);
    TEST_ASSERT_OK(ret, "event_wait (after set)");

    /* 手动重置: 不会自动清除 */
    ret = ainos_platform_event_wait(&event);
    TEST_ASSERT_OK(ret, "event_wait second (manual)");

    ret = ainos_platform_event_reset(&event);
    TEST_ASSERT_OK(ret, "event_reset");

    ainos_platform_event_destroy(&event);
    return 0;
}

static int test_event_auto_reset(void)
{
    ainos_platform_event_t event;
    int ret = ainos_platform_event_init(&event, 0, 0);
    TEST_ASSERT_OK(ret, "event_init auto");

    ret = ainos_platform_event_set(&event);
    TEST_ASSERT_OK(ret, "event_set");

    ret = ainos_platform_event_wait(&event);
    TEST_ASSERT_OK(ret, "event_wait (auto)");

    /* 自动重置: 已自动清除 */
    ret = ainos_platform_event_timedwait(&event, 10);
    TEST_ASSERT_EQ(ret, AINOS_PLATFORM_ERR_TIMEOUT, "event_timedwait (auto reset)");

    ainos_platform_event_destroy(&event);
    return 0;
}

/* ================================================================
 * 屏障测试
 * ================================================================ */

static ainos_platform_barrier_t g_barrier;
static int g_barrier_count = 0;

static int barrier_worker(void* arg)
{
    (void)arg;
    ainos_platform_barrier_wait(&g_barrier);
    g_barrier_count++;
    return 0;
}

static int test_barrier(void)
{
    int ret = ainos_platform_barrier_init(&g_barrier, 3);
    TEST_ASSERT_OK(ret, "barrier_init");

    g_barrier_count = 0;
    ainos_platform_thread_t t1, t2;
    ainos_platform_thread_create(&t1, NULL, barrier_worker, NULL);
    ainos_platform_thread_create(&t2, NULL, barrier_worker, NULL);

    /* 主线程等待 */
    ret = ainos_platform_barrier_wait(&g_barrier);
    /* 最后一个到达的线程可能返回非零 */
    ainos_platform_thread_join(&t1, NULL);
    ainos_platform_thread_join(&t2, NULL);

    ainos_platform_barrier_destroy(&g_barrier);
    return 0;
}

/* ================================================================
 * Socket 测试
 * ================================================================ */

static int test_socket_create_close(void)
{
    ainos_platform_socket_t sock;
    int ret = ainos_platform_socket_create(&sock, AINOS_PLATFORM_AF_INET,
                                           AINOS_PLATFORM_SOCK_STREAM, 0);
    TEST_ASSERT_OK(ret, "socket_create");
    TEST_ASSERT(ainos_platform_socket_is_valid(&sock), "socket_is_valid");

    ret = ainos_platform_socket_close(&sock);
    TEST_ASSERT_OK(ret, "socket_close");
    TEST_ASSERT(!ainos_platform_socket_is_valid(&sock), "socket_is_valid after close");
    return 0;
}

static int test_socket_bind_connect(void)
{
    ainos_platform_socket_t server;
    ainos_platform_socket_create(&server, AINOS_PLATFORM_AF_INET,
                                 AINOS_PLATFORM_SOCK_STREAM, 0);

    ainos_platform_sockaddr_t addr;
    ainos_platform_sockaddr_set_inet4(&addr, "127.0.0.1", 0);

    int ret = ainos_platform_socket_bind(&server, &addr);
    TEST_ASSERT_OK(ret, "socket_bind");

    ret = ainos_platform_socket_listen(&server, 5);
    TEST_ASSERT_OK(ret, "socket_listen");

    /* 获取实际分配的端口 */
    ainos_platform_sockaddr_t local_addr;
    ainos_platform_socket_get_local_addr(&server, &local_addr);
    uint16_t port = 0;
    ainos_platform_sockaddr_get_inet4(&local_addr, NULL, 0, &port);
    TEST_ASSERT_NE(port, 0, "socket bound port non-zero");

    /* 客户端连接 */
    ainos_platform_socket_t client;
    ainos_platform_sockaddr_set_inet4(&addr, "127.0.0.1", port);
    ainos_platform_socket_create(&client, AINOS_PLATFORM_AF_INET,
                                 AINOS_PLATFORM_SOCK_STREAM, 0);
    ret = ainos_platform_socket_connect(&client, &addr);
    TEST_ASSERT_OK(ret, "socket_connect");

    /* 服务器接受 */
    ainos_platform_socket_t accepted;
    ret = ainos_platform_socket_accept(&server, &accepted, NULL);
    TEST_ASSERT_OK(ret, "socket_accept");

    ainos_platform_socket_close(&accepted);
    ainos_platform_socket_close(&client);
    ainos_platform_socket_close(&server);
    return 0;
}

static int test_socket_send_recv(void)
{
    ainos_platform_socket_t server, client, accepted;
    ainos_platform_socket_create(&server, AINOS_PLATFORM_AF_INET,
                                 AINOS_PLATFORM_SOCK_STREAM, 0);
    ainos_platform_sockaddr_t addr;
    ainos_platform_sockaddr_set_inet4(&addr, "127.0.0.1", 0);
    ainos_platform_socket_bind(&server, &addr);
    ainos_platform_socket_listen(&server, 5);

    ainos_platform_sockaddr_t local;
    ainos_platform_socket_get_local_addr(&server, &local);
    uint16_t port = 0;
    ainos_platform_sockaddr_get_inet4(&local, NULL, 0, &port);

    ainos_platform_socket_create(&client, AINOS_PLATFORM_AF_INET,
                                 AINOS_PLATFORM_SOCK_STREAM, 0);
    ainos_platform_sockaddr_set_inet4(&addr, "127.0.0.1", port);
    ainos_platform_socket_connect(&client, &addr);
    ainos_platform_socket_accept(&server, &accepted, NULL);

    const char* test_data = "Hello AinosOS!";
    int sent = ainos_platform_socket_send(&client, test_data,
                                          (int)strlen(test_data), 0);
    TEST_ASSERT_EQ(sent, (int)strlen(test_data), "socket_send bytes");

    char buf[256] = {0};
    int recvd = ainos_platform_socket_recv(&accepted, buf, sizeof(buf) - 1, 0);
    TEST_ASSERT_EQ(recvd, (int)strlen(test_data), "socket_recv bytes");
    TEST_ASSERT_EQ(strcmp(buf, test_data), 0, "socket_recv data");

    ainos_platform_socket_close(&accepted);
    ainos_platform_socket_close(&client);
    ainos_platform_socket_close(&server);
    return 0;
}

static int test_socket_nonblocking(void)
{
    ainos_platform_socket_t sock;
    ainos_platform_socket_create(&sock, AINOS_PLATFORM_AF_INET,
                                 AINOS_PLATFORM_SOCK_STREAM, 0);

    int ret = ainos_platform_socket_set_nonblocking(&sock, 1);
    TEST_ASSERT_OK(ret, "socket_set_nonblocking(1)");

    ret = ainos_platform_socket_set_nonblocking(&sock, 0);
    TEST_ASSERT_OK(ret, "socket_set_nonblocking(0)");

    ainos_platform_socket_close(&sock);
    return 0;
}

/* ================================================================
 * 地址构造测试
 * ================================================================ */

static int test_sockaddr_inet4(void)
{
    ainos_platform_sockaddr_t addr;
    int ret = ainos_platform_sockaddr_set_inet4(&addr, "192.168.1.1", 8080);
    TEST_ASSERT_OK(ret, "sockaddr_set_inet4");

    int family = ainos_platform_sockaddr_get_family(&addr);
    TEST_ASSERT_EQ(family, AINOS_PLATFORM_AF_INET, "sockaddr family");

    char ip[64] = {0};
    uint16_t port = 0;
    ret = ainos_platform_sockaddr_get_inet4(&addr, ip, sizeof(ip), &port);
    TEST_ASSERT_OK(ret, "sockaddr_get_inet4");
    TEST_ASSERT_EQ(strcmp(ip, "192.168.1.1"), 0, "sockaddr ip");
    TEST_ASSERT_EQ(port, 8080, "sockaddr port");
    return 0;
}

/* ================================================================
 * File I/O 测试
 * ================================================================ */

static int test_file_open_close(void)
{
    ainos_platform_file_t file;
    int ret = ainos_platform_file_open(&file, "test_platform_tmp.txt",
                                       AINOS_PLATFORM_FILE_O_CREAT |
                                       AINOS_PLATFORM_FILE_O_WRONLY |
                                       AINOS_PLATFORM_FILE_O_TRUNC, 0644);
    TEST_ASSERT_OK(ret, "file_open (create)");

    ret = ainos_platform_file_close(&file);
    TEST_ASSERT_OK(ret, "file_close");

    ainos_platform_file_unlink("test_platform_tmp.txt");
    return 0;
}

static int test_file_read_write(void)
{
    const char* test_data = "AinosOS Platform Test: Hello, World!";
    size_t data_len = strlen(test_data);

    /* 写入文件 */
    ainos_platform_file_t file;
    ainos_platform_file_open(&file, "test_platform_rw.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY |
                             AINOS_PLATFORM_FILE_O_TRUNC, 0644);

    int64_t written = ainos_platform_file_write(&file, test_data, (int64_t)data_len);
    TEST_ASSERT_EQ(written, (int64_t)data_len, "file_write bytes");
    ainos_platform_file_close(&file);

    /* 读取文件 */
    ainos_platform_file_open(&file, "test_platform_rw.txt",
                             AINOS_PLATFORM_FILE_O_RDONLY, 0);

    char buf[256] = {0};
    int64_t read = ainos_platform_file_read(&file, buf, sizeof(buf) - 1);
    TEST_ASSERT_EQ(read, (int64_t)data_len, "file_read bytes");
    TEST_ASSERT_EQ(strcmp(buf, test_data), 0, "file_read data");
    ainos_platform_file_close(&file);

    ainos_platform_file_unlink("test_platform_rw.txt");
    return 0;
}

static int test_file_seek(void)
{
    ainos_platform_file_t file;
    ainos_platform_file_open(&file, "test_platform_seek.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY, 0644);
    ainos_platform_file_write(&file, "ABCDEFGHIJ", 10);
    ainos_platform_file_close(&file);

    ainos_platform_file_open(&file, "test_platform_seek.txt",
                             AINOS_PLATFORM_FILE_O_RDONLY, 0);

    ainos_platform_file_seek(&file, 3, AINOS_PLATFORM_FILE_SEEK_SET);
    int64_t pos = ainos_platform_file_tell(&file);
    TEST_ASSERT_EQ(pos, 3, "file_tell after seek set");

    char buf[16] = {0};
    ainos_platform_file_read(&file, buf, 4);
    TEST_ASSERT_EQ(strncmp(buf, "DEFG", 4), 0, "file_read after seek");

    ainos_platform_file_close(&file);
    ainos_platform_file_unlink("test_platform_seek.txt");
    return 0;
}

static int test_file_stat(void)
{
    ainos_platform_file_stat_t st;
    int ret = ainos_platform_file_stat("test_platform_stat.txt", &st);
    TEST_ASSERT_ERR(ret, "file_stat (non-existent)");

    /* 创建文件后 stat */
    ainos_platform_file_t file;
    ainos_platform_file_open(&file, "test_platform_stat.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY, 0644);
    ainos_platform_file_write(&file, "test", 4);
    ainos_platform_file_close(&file);

    ret = ainos_platform_file_stat("test_platform_stat.txt", &st);
    TEST_ASSERT_OK(ret, "file_stat (exists)");
    TEST_ASSERT(st.size > 0, "file_stat size > 0");
    TEST_ASSERT(!st.is_directory, "file_stat is not dir");

    ainos_platform_file_unlink("test_platform_stat.txt");
    return 0;
}

static int test_file_exists_rename(void)
{
    ainos_platform_file_t file;
    ainos_platform_file_open(&file, "test_platform_old.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY, 0644);
    ainos_platform_file_write(&file, "rename test", 11);
    ainos_platform_file_close(&file);

    TEST_ASSERT(ainos_platform_file_exists("test_platform_old.txt"),
                "file_exists before rename");

    ainos_platform_file_rename("test_platform_old.txt", "test_platform_new.txt");
    TEST_ASSERT(!ainos_platform_file_exists("test_platform_old.txt"),
                "file_exists old after rename");
    TEST_ASSERT(ainos_platform_file_exists("test_platform_new.txt"),
                "file_exists new after rename");

    ainos_platform_file_unlink("test_platform_new.txt");
    return 0;
}

/* ================================================================
 * 目录操作测试
 * ================================================================ */

static int test_dir_mkdir_rmdir(void)
{
    int ret = ainos_platform_dir_mkdir("test_platform_dir", 0755);
    TEST_ASSERT_OK(ret, "dir_mkdir");

    TEST_ASSERT(ainos_platform_file_exists("test_platform_dir"),
                "dir exists after mkdir");

    ainos_platform_dir_rmdir("test_platform_dir");
    TEST_ASSERT(!ainos_platform_file_exists("test_platform_dir"),
                "dir gone after rmdir");
    return 0;
}

static int test_dir_open_read(void)
{
    ainos_platform_dir_mkdir("test_platform_readdir", 0755);

    /* 创建一些文件 */
    ainos_platform_file_t f;
    ainos_platform_file_open(&f, "test_platform_readdir/file1.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY, 0644);
    ainos_platform_file_close(&f);
    ainos_platform_file_open(&f, "test_platform_readdir/file2.txt",
                             AINOS_PLATFORM_FILE_O_CREAT |
                             AINOS_PLATFORM_FILE_O_WRONLY, 0644);
    ainos_platform_file_close(&f);

    ainos_platform_dir_t dir;
    int ret = ainos_platform_dir_open(&dir, "test_platform_readdir");
    TEST_ASSERT_OK(ret, "dir_open");

    ainos_platform_dirent_t entry;
    int found_files = 0;
    while (ainos_platform_dir_read(&dir, &entry) > 0) {
        if (strcmp(entry.name, ".") != 0 && strcmp(entry.name, "..") != 0) {
            found_files++;
        }
    }
    TEST_ASSERT_EQ(found_files, 2, "dir_read found 2 files");

    ainos_platform_dir_close(&dir);

    ainos_platform_dir_rmdir_r("test_platform_readdir");
    return 0;
}

/* ================================================================
 * 内存管理测试
 * ================================================================ */

static int test_mem_alloc_free(void)
{
    void* ptr = ainos_platform_mem_alloc(1024);
    TEST_ASSERT_NE(ptr, NULL, "mem_alloc 1KB");
    ainos_platform_mem_free(ptr);
    return 0;
}

static int test_mem_calloc(void)
{
    int* arr = (int*)ainos_platform_mem_calloc(100, sizeof(int));
    TEST_ASSERT_NE(arr, NULL, "mem_calloc 100 ints");
    for (int i = 0; i < 100; i++) {
        TEST_ASSERT_EQ(arr[i], 0, "calloc zeroed");
    }
    ainos_platform_mem_free(arr);
    return 0;
}

static int test_mem_realloc(void)
{
    int* arr = (int*)ainos_platform_mem_alloc(10 * sizeof(int));
    TEST_ASSERT_NE(arr, NULL, "realloc initial alloc");

    for (int i = 0; i < 10; i++) arr[i] = i;

    int* new_arr = (int*)ainos_platform_mem_realloc(arr, 20 * sizeof(int));
    TEST_ASSERT_NE(new_arr, NULL, "realloc grow");
    TEST_ASSERT_EQ(new_arr[0], 0, "realloc data preserved");
    TEST_ASSERT_EQ(new_arr[9], 9, "realloc data preserved");

    ainos_platform_mem_free(new_arr);
    return 0;
}

static int test_mem_aligned_alloc(void)
{
    void* ptr = ainos_platform_mem_aligned_alloc(256, 1024);
    TEST_ASSERT_NE(ptr, NULL, "aligned_alloc 256-byte aligned");
    TEST_ASSERT(((uintptr_t)ptr & 0xFF) == 0, "aligned_alloc alignment");
    ainos_platform_mem_aligned_free(ptr);
    return 0;
}

static int test_mem_page_size(void)
{
    int page_size = ainos_platform_mem_get_page_size();
    TEST_ASSERT(page_size > 0, "page_size > 0");
    TEST_ASSERT(page_size >= 512, "page_size >= 512");
    return 0;
}

static int test_mem_available(void)
{
    int64_t avail = ainos_platform_mem_get_available_memory();
    TEST_ASSERT(avail > 0, "available_memory > 0");
    int64_t total = ainos_platform_mem_get_total_physical_memory();
    TEST_ASSERT(total > 0, "total_memory > 0");
    TEST_ASSERT(avail <= total, "available <= total");
    return 0;
}

/* ================================================================
 * 原子操作测试
 * ================================================================ */

static int test_atomic32(void)
{
    ainos_platform_atomic32_t atomic;
    ainos_platform_atomic32_init(&atomic, 42);

    int32_t val = ainos_platform_atomic32_load(&atomic);
    TEST_ASSERT_EQ(val, 42, "atomic32_load initial");

    ainos_platform_atomic32_store(&atomic, 100);
    val = ainos_platform_atomic32_load(&atomic);
    TEST_ASSERT_EQ(val, 100, "atomic32_store");

    val = ainos_platform_atomic32_exchange(&atomic, 200);
    TEST_ASSERT_EQ(val, 100, "atomic32_exchange old");

    val = ainos_platform_atomic32_fetch_add(&atomic, 5);
    TEST_ASSERT_EQ(val, 200, "atomic32_fetch_add old");

    val = ainos_platform_atomic32_load(&atomic);
    TEST_ASSERT_EQ(val, 205, "atomic32_fetch_add new");

    val = ainos_platform_atomic32_compare_exchange(&atomic, 205, 300);
    TEST_ASSERT_EQ(val, 205, "atomic32_cas old");

    val = ainos_platform_atomic32_load(&atomic);
    TEST_ASSERT_EQ(val, 300, "atomic32_cas new");
    return 0;
}

static int test_atomic64(void)
{
    ainos_platform_atomic64_t atomic;
    ainos_platform_atomic64_init(&atomic, 0xDEADBEEF);

    int64_t val = ainos_platform_atomic64_load(&atomic);
    TEST_ASSERT_EQ(val, 0xDEADBEEF, "atomic64_load");

    ainos_platform_atomic64_store(&atomic, 0xCAFEBABE);
    val = ainos_platform_atomic64_exchange(&atomic, 0x12345678);
    TEST_ASSERT_EQ(val, 0xCAFEBABE, "atomic64_exchange");

    val = ainos_platform_atomic64_fetch_add(&atomic, 1000);
    TEST_ASSERT_EQ(val, 0x12345678, "atomic64_fetch_add");
    return 0;
}

/* ================================================================
 * 时间 API 测试
 * ================================================================ */

static int test_time_now(void)
{
    ainos_platform_time_t t;
    int ret = ainos_platform_time_now(&t);
    TEST_ASSERT_OK(ret, "time_now");
    TEST_ASSERT(t.seconds > 1700000000, "time_now seconds > 2023");
    TEST_ASSERT(t.nanoseconds >= 0 && t.nanoseconds < 1000000000,
                "time_now nanoseconds valid");
    return 0;
}

static int test_time_now_ms(void)
{
    int64_t ms = ainos_platform_time_now_ms();
    TEST_ASSERT(ms > 1700000000000LL, "time_now_ms > 2023");
    return 0;
}

static int test_time_monotonic(void)
{
    int64_t t1 = ainos_platform_time_monotonic_ns();
    ainos_platform_time_sleep_ms(10);
    int64_t t2 = ainos_platform_time_monotonic_ns();
    TEST_ASSERT(t2 > t1, "monotonic increasing");
    int64_t diff = t2 - t1;
    TEST_ASSERT(diff >= 5000000, "monotonic diff >= 5ms");
    return 0;
}

static int test_time_sleep(void)
{
    int64_t start = ainos_platform_time_now_ms();
    int ret = ainos_platform_time_sleep_ms(30);
    int64_t elapsed = ainos_platform_time_now_ms() - start;
    TEST_ASSERT_OK(ret, "time_sleep_ms");
    TEST_ASSERT(elapsed >= 25, "sleep_ms >= 25ms");
    return 0;
}

static int test_time_format(void)
{
    ainos_platform_time_t t;
    ainos_platform_time_now(&t);

    char buf[64] = {0};
    int ret = ainos_platform_time_format(&t, "%Y-%m-%d", buf, sizeof(buf));
    TEST_ASSERT_OK(ret, "time_format");
    TEST_ASSERT(strlen(buf) == 10, "time_format length 10");
    return 0;
}

static int test_time_iso8601(void)
{
    char buf[64] = {0};
    int ret = ainos_platform_time_format_iso8601(buf, sizeof(buf));
    TEST_ASSERT_OK(ret, "time_format_iso8601");
    TEST_ASSERT(strlen(buf) > 20, "iso8601 length > 20");
    return 0;
}

static int test_time_diff(void)
{
    ainos_platform_time_t t1, t2;
    ainos_platform_time_now(&t1);
    ainos_platform_time_sleep_ms(15);
    ainos_platform_time_now(&t2);

    int64_t diff = ainos_platform_time_diff_ms(&t2, &t1);
    TEST_ASSERT(diff >= 10, "time_diff_ms >= 10ms");
    return 0;
}

/* ================================================================
 * 进程管理测试
 * ================================================================ */

static int test_process_get_pid(void)
{
    int pid = ainos_platform_process_get_pid();
    TEST_ASSERT(pid > 0, "get_pid > 0");
    return 0;
}

static int test_process_get_name(void)
{
    char name[256] = {0};
    int ret = ainos_platform_process_get_name(name, sizeof(name));
    TEST_ASSERT_OK(ret, "process_get_name");
    TEST_ASSERT(strlen(name) > 0, "process name non-empty");
    return 0;
}

static int test_process_get_path(void)
{
    char path[1024] = {0};
    int ret = ainos_platform_process_get_path(path, sizeof(path));
    TEST_ASSERT_OK(ret, "process_get_path");
    TEST_ASSERT(strlen(path) > 0, "process path non-empty");
    return 0;
}

/* ================================================================
 * 动态库测试
 * ================================================================ */

static int test_dl_self_path(void)
{
    char buf[1024] = {0};
    int ret = ainos_platform_dlget_self_path(buf, sizeof(buf));
    TEST_ASSERT_OK(ret, "dlget_self_path");
    TEST_ASSERT(strlen(buf) > 0, "self path non-empty");
    return 0;
}

/* ================================================================
 * 环境变量测试
 * ================================================================ */

static int test_env_get_set(void)
{
    const char* val = ainos_platform_getenv("PATH");
    TEST_ASSERT_NE(val, NULL, "getenv PATH");

    /* 设置测试环境变量 */
    int ret = ainos_platform_setenv("AINOS_TEST_VAR", "test_value", 1);
    TEST_ASSERT_OK(ret, "setenv");

    val = ainos_platform_getenv("AINOS_TEST_VAR");
    TEST_ASSERT_NE(val, NULL, "getenv AINOS_TEST_VAR");
    TEST_ASSERT_EQ(strcmp(val, "test_value"), 0, "getenv value");

    ret = ainos_platform_unsetenv("AINOS_TEST_VAR");
    TEST_ASSERT_OK(ret, "unsetenv");

    val = ainos_platform_getenv("AINOS_TEST_VAR");
    TEST_ASSERT_EQ(val, NULL, "getenv after unset");
    return 0;
}

/* ========================================
 * 系统信息测试
 * ======================================== */

static int test_sys_cpu_info(void)
{
    ainos_platform_cpu_info_t info;
    int ret = ainos_platform_sys_get_cpu_info(&info);
    TEST_ASSERT_OK(ret, "sys_get_cpu_info");
    TEST_ASSERT(info.logical_cores > 0, "logical_cores > 0");
    TEST_ASSERT(info.physical_cores > 0, "physical_cores > 0");
    return 0;
}

static int test_sys_hostname(void)
{
    char buf[256] = {0};
    int ret = ainos_platform_sys_get_hostname(buf, sizeof(buf));
    TEST_ASSERT_OK(ret, "sys_get_hostname");
    TEST_ASSERT(strlen(buf) > 0, "hostname non-empty");
    return 0;
}

static int test_sys_os_info(void)
{
    char name[64] = {0}, version[128] = {0};
    int ret = ainos_platform_sys_get_os_info(name, sizeof(name),
                                              version, sizeof(version));
    TEST_ASSERT_OK(ret, "sys_get_os_info");
    TEST_ASSERT(strlen(name) > 0, "os name non-empty");
    return 0;
}

/* ========================================
 * UUID 测试
 * ======================================== */

static int test_uuid_generate(void)
{
    char buf[37] = {0};
    int ret = ainos_platform_uuid_v4_generate(buf, sizeof(buf));
    TEST_ASSERT_OK(ret, "uuid_v4_generate");
    TEST_ASSERT_EQ(strlen(buf), 36, "uuid length 36");
    TEST_ASSERT_EQ(buf[8], '-', "uuid format dash");
    TEST_ASSERT_EQ(buf[13], '-', "uuid format dash");
    TEST_ASSERT_EQ(buf[18], '-', "uuid format dash");
    TEST_ASSERT_EQ(buf[23], '-', "uuid format dash");
    return 0;
}

/* ========================================
 * 控制台测试
 * ======================================== */

static int test_console_dimensions(void)
{
    int width = ainos_platform_console_get_width();
    TEST_ASSERT(width > 0, "console width > 0");
    int height = ainos_platform_console_get_height();
    TEST_ASSERT(height > 0, "console height > 0");
    return 0;
}

/* ================================================================
 * 测试运行器
 * ================================================================ */

typedef struct {
    const char* name;
    const char* flag;
    int (*func)(void);
} test_entry_t;

static test_entry_t g_all_tests[] = {
    {"Mutex Init/Destroy",       "--mutex",    test_mutex_init_destroy},
    {"Mutex Lock/Unlock",        "--mutex",    test_mutex_lock_unlock},
    {"Mutex Trylock",            "--mutex",    test_mutex_trylock},
    {"Mutex Recursive",          "--mutex",    test_mutex_recursive},
    {"Mutex Invalid",            "--mutex",    test_mutex_invalid},
    {"Mutex Contention",         "--mutex",    test_mutex_contention},
    {"Thread Create/Join",       "--thread",   test_thread_create_join},
    {"Thread Self ID",           "--thread",   test_thread_self_id},
    {"Thread Sleep",             "--thread",   test_thread_sleep},
    {"Thread Name",              "--thread",   test_thread_name},
    {"RWLock Read/Write",        "--thread",   test_rwlock_read_write},
    {"CondVar Signal/Wait",      "--thread",   test_cond_signal_wait},
    {"Semaphore Init/Wait/Post", "--thread",   test_semaphore_init_wait_post},
    {"Event Manual Reset",       "--thread",   test_event_manual_reset},
    {"Event Auto Reset",         "--thread",   test_event_auto_reset},
    {"Barrier",                  "--thread",   test_barrier},
    {"Socket Create/Close",      "--socket",   test_socket_create_close},
    {"Socket Bind/Connect",      "--socket",   test_socket_bind_connect},
    {"Socket Send/Recv",         "--socket",   test_socket_send_recv},
    {"Socket Nonblocking",       "--socket",   test_socket_nonblocking},
    {"Sockaddr IPv4",            "--socket",   test_sockaddr_inet4},
    {"File Open/Close",          "--file",     test_file_open_close},
    {"File Read/Write",          "--file",     test_file_read_write},
    {"File Seek",                "--file",     test_file_seek},
    {"File Stat",                "--file",     test_file_stat},
    {"File Exists/Rename",       "--file",     test_file_exists_rename},
    {"Dir Mkdir/Rmdir",          "--file",     test_dir_mkdir_rmdir},
    {"Dir Open/Read",            "--file",     test_dir_open_read},
    {"Memory Alloc/Free",        "--memory",   test_mem_alloc_free},
    {"Memory Calloc",            "--memory",   test_mem_calloc},
    {"Memory Realloc",           "--memory",   test_mem_realloc},
    {"Memory Aligned",           "--memory",   test_mem_aligned_alloc},
    {"Memory Page Size",         "--memory",   test_mem_page_size},
    {"Memory Available",         "--memory",   test_mem_available},
    {"Atomic32",                 "--memory",   test_atomic32},
    {"Atomic64",                 "--memory",   test_atomic64},
    {"Time Now",                 "--time",     test_time_now},
    {"Time Now Ms",              "--time",     test_time_now_ms},
    {"Time Monotonic",           "--time",     test_time_monotonic},
    {"Time Sleep",               "--time",     test_time_sleep},
    {"Time Format",              "--time",     test_time_format},
    {"Time ISO8601",             "--time",     test_time_iso8601},
    {"Time Diff",                "--time",     test_time_diff},
    {"Process Get PID",          "--process",  test_process_get_pid},
    {"Process Get Name",         "--process",  test_process_get_name},
    {"Process Get Path",         "--process",  test_process_get_path},
    {"Dynamic Lib Self Path",    "--dl",       test_dl_self_path},
    {"Environment Get/Set",      "--env",      test_env_get_set},
    {"System CPU Info",          "--sys",      test_sys_cpu_info},
    {"System Hostname",          "--sys",      test_sys_hostname},
    {"System OS Info",           "--sys",      test_sys_os_info},
    {"UUID Generate",            "--uuid",     test_uuid_generate},
    {"Console Dimensions",       "--console",  test_console_dimensions},
};

static const int g_test_count = sizeof(g_all_tests) / sizeof(g_all_tests[0]);

int main(int argc, char* argv[])
{
    /* 初始化平台 */
    int ret = ainos_platform_init();
    if (ret != AINOS_PLATFORM_OK) {
        printf("FAIL: ainos_platform_init() returned %d\n", ret);
        return 1;
    }

    printf("AinosOS Platform Abstraction Layer - Unit Tests\n");
    printf("Platform: %s v%s\n", ainos_platform_name(), ainos_platform_version());
    printf("=====================================================\n\n");

    /* 解析命令行参数 */
    const char* filter = NULL;
    int list_tests = 0;

    if (argc > 1) {
        if (strcmp(argv[1], "--list") == 0) {
            list_tests = 1;
        } else if (argv[1][0] == '-') {
            filter = argv[1];
        }
    }

    if (list_tests) {
        printf("Available tests:\n");
        const char* last_flag = "";
        for (int i = 0; i < g_test_count; i++) {
            if (strcmp(g_all_tests[i].flag, last_flag) != 0) {
                printf("\n  %s:\n", g_all_tests[i].flag);
                last_flag = g_all_tests[i].flag;
            }
            printf("    %s\n", g_all_tests[i].name);
        }
        ainos_platform_cleanup();
        return 0;
    }

    /* 运行测试 */
    for (int i = 0; i < g_test_count; i++) {
        if (filter && strcmp(g_all_tests[i].flag, filter) != 0) {
            continue;
        }
        RUN_TEST(g_all_tests[i].name);
        /* 使用 RUN_TEST 宏调用 */
        (void)(g_all_tests[i].func);
    }

    printf("\n=====================================================\n");
    printf("Results: %d passed, %d failed, %d assertions passed, %d assertions failed\n",
           g_tests_passed, g_tests_failed,
           g_assertions_passed, g_assertions_failed);

    ainos_platform_cleanup();

    return g_tests_failed > 0 ? 1 : 0;
}