# AinosOS 平台抽象层架构文档

## 概述

平台抽象层 (Platform Abstraction Layer, PAL) 是 AinosOS 的核心基础组件，提供统一的跨平台 API 接口，屏蔽不同操作系统和硬件平台之间的差异。PAL 包含 31 个 API 组，涵盖线程管理、内存管理、文件系统、网络通信、时间同步等各个方面。

## 架构设计

```
+------------------------------------------+
|           用户态应用程序                    |
+------------------------------------------+
|          AinosOS 系统服务层               |
+------------------------------------------+
|         平台抽象层 (PAL)                  |
+-----------+-----------+-----------+------+
|  Windows  |  Linux    |  macOS    |  BSD  |
|  PAL impl | PAL impl  | PAL impl  | impl  |
+-----------+-----------+-----------+------+
|     Win32 | POSIX     |  Darwin   | POSIX |
|     API   | API       |  API      | API   |
+-----------+-----------+-----------+------+
```

## 31 个 API 组

### 1. 线程管理 (Thread)

```c
// 头文件: <ainos/pal/thread.h>

// 创建线程
typedef void* (*ainos_thread_func)(void* arg);
int ainos_thread_create(ainos_thread_t* thread, ainos_thread_func func, 
                         void* arg, const ainos_thread_attr_t* attr);

// 等待线程结束
int ainos_thread_join(ainos_thread_t thread, void** retval);

// 分离线程
int ainos_thread_detach(ainos_thread_t thread);

// 退出当前线程
void ainos_thread_exit(void* retval);

// 获取当前线程 ID
ainos_thread_id_t ainos_thread_self(void);

// 线程属性操作
int ainos_thread_attr_init(ainos_thread_attr_t* attr);
int ainos_thread_attr_set_stack_size(ainos_thread_attr_t* attr, size_t size);
int ainos_thread_attr_set_priority(ainos_thread_attr_t* attr, int priority);
int ainos_thread_attr_set_affinity(ainos_thread_attr_t* attr, uint64_t cpu_mask);
int ainos_thread_attr_destroy(ainos_thread_attr_t* attr);

// 线程同步
int ainos_thread_yield(void);
int ainos_thread_sleep(uint64_t milliseconds);
```

### 2. 互斥锁 (Mutex)

```c
// 头文件: <ainos/pal/mutex.h>

int ainos_mutex_init(ainos_mutex_t* mutex, const ainos_mutex_attr_t* attr);
int ainos_mutex_destroy(ainos_mutex_t* mutex);
int ainos_mutex_lock(ainos_mutex_t* mutex);
int ainos_mutex_trylock(ainos_mutex_t* mutex);
int ainos_mutex_unlock(ainos_mutex_t* mutex);

// 递归互斥锁
int ainos_mutex_init_recursive(ainos_mutex_t* mutex);
```

### 3. 读写锁 (RWLock)

```c
// 头文件: <ainos/pal/rwlock.h>

int ainos_rwlock_init(ainos_rwlock_t* rwlock);
int ainos_rwlock_destroy(ainos_rwlock_t* rwlock);
int ainos_rwlock_rdlock(ainos_rwlock_t* rwlock);
int ainos_rwlock_wrlock(ainos_rwlock_t* rwlock);
int ainos_rwlock_tryrdlock(ainos_rwlock_t* rwlock);
int ainos_rwlock_trywrlock(ainos_rwlock_t* rwlock);
int ainos_rwlock_unlock(ainos_rwlock_t* rwlock);
```

### 4. 条件变量 (Condition Variable)

```c
// 头文件: <ainos/pal/cond.h>

int ainos_cond_init(ainos_cond_t* cond);
int ainos_cond_destroy(ainos_cond_t* cond);
int ainos_cond_wait(ainos_cond_t* cond, ainos_mutex_t* mutex);
int ainos_cond_timedwait(ainos_cond_t* cond, ainos_mutex_t* mutex, 
                          uint64_t timeout_ms);
int ainos_cond_signal(ainos_cond_t* cond);
int ainos_cond_broadcast(ainos_cond_t* cond);
```

### 5. 信号量 (Semaphore)

```c
// 头文件: <ainos/pal/sem.h>

int ainos_sem_init(ainos_sem_t* sem, uint32_t value);
int ainos_sem_destroy(ainos_sem_t* sem);
int ainos_sem_wait(ainos_sem_t* sem);
int ainos_sem_trywait(ainos_sem_t* sem);
int ainos_sem_timedwait(ainos_sem_t* sem, uint64_t timeout_ms);
int ainos_sem_post(ainos_sem_t* sem);
int ainos_sem_getvalue(ainos_sem_t* sem, int* sval);
```

### 6. 屏障 (Barrier)

```c
// 头文件: <ainos/pal/barrier.h>

int ainos_barrier_init(ainos_barrier_t* barrier, uint32_t count);
int ainos_barrier_destroy(ainos_barrier_t* barrier);
int ainos_barrier_wait(ainos_barrier_t* barrier);
```

### 7. 原子操作 (Atomic)

```c
// 头文件: <ainos/pal/atomic.h>

int32_t ainos_atomic_add(volatile int32_t* ptr, int32_t val);
int64_t ainos_atomic_add64(volatile int64_t* ptr, int64_t val);
int32_t ainos_atomic_sub(volatile int32_t* ptr, int32_t val);
int32_t ainos_atomic_exchange(volatile int32_t* ptr, int32_t val);
int32_t ainos_atomic_cas(volatile int32_t* ptr, int32_t old_val, int32_t new_val);
void* ainos_atomic_ptr_cas(volatile void** ptr, void* old_val, void* new_val);
int32_t ainos_atomic_load(volatile int32_t* ptr);
void ainos_atomic_store(volatile int32_t* ptr, int32_t val);

// 内存屏障
void ainos_memory_barrier(void);
void ainos_memory_acquire(void);
void ainos_memory_release(void);
```

### 8. 线程本地存储 (TLS)

```c
// 头文件: <ainos/pal/tls.h>

int ainos_tls_key_create(ainos_tls_key_t* key, void (*destructor)(void*));
int ainos_tls_key_delete(ainos_tls_key_t key);
int ainos_tls_set(ainos_tls_key_t key, void* value);
void* ainos_tls_get(ainos_tls_key_t key);
```

### 9. 内存管理 (Memory)

```c
// 头文件: <ainos/pal/memory.h>

void* ainos_malloc(size_t size);
void* ainos_calloc(size_t nmemb, size_t size);
void* ainos_realloc(void* ptr, size_t size);
void ainos_free(void* ptr);

// 对齐内存分配
void* ainos_aligned_alloc(size_t alignment, size_t size);
void ainos_aligned_free(void* ptr);

// 大页内存
void* ainos_hugepage_alloc(size_t size, size_t* actual_size);
int ainos_hugepage_free(void* ptr, size_t size);

// 内存映射
void* ainos_mmap(void* addr, size_t length, int prot, int flags, 
                  int fd, int64_t offset);
int ainos_munmap(void* addr, size_t length);

// 内存保护
int ainos_mprotect(void* addr, size_t length, int prot);

// 内存锁定
int ainos_mlock(const void* addr, size_t length);
int ainos_munlock(const void* addr, size_t length);

// 内存信息
int ainos_meminfo(uint64_t* total, uint64_t* free, uint64_t* available);
```

### 10. 文件系统 (File System)

```c
// 头文件: <ainos/pal/fs.h>

// 文件操作
int ainos_file_open(ainos_file_t* file, const char* path, int flags, int mode);
int ainos_file_close(ainos_file_t file);
int64_t ainos_file_read(ainos_file_t file, void* buf, uint64_t count);
int64_t ainos_file_write(ainos_file_t file, const void* buf, uint64_t count);
int64_t ainos_file_seek(ainos_file_t file, int64_t offset, int whence);
int64_t ainos_file_tell(ainos_file_t file);
int ainos_file_truncate(ainos_file_t file, int64_t length);
int ainos_file_sync(ainos_file_t file);
int ainos_file_size(ainos_file_t file, uint64_t* size);

// 目录操作
int ainos_dir_open(ainos_dir_t* dir, const char* path);
int ainos_dir_read(ainos_dir_t dir, struct ainos_dirent* entry);
int ainos_dir_close(ainos_dir_t dir);
int ainos_mkdir(const char* path, int mode);
int ainos_rmdir(const char* path);

// 路径操作
int ainos_stat(const char* path, struct ainos_stat* buf);
int ainos_access(const char* path, int mode);
int ainos_unlink(const char* path);
int ainos_rename(const char* oldpath, const char* newpath);
int ainos_link(const char* oldpath, const char* newpath);
int ainos_symlink(const char* target, const char* linkpath);
int ainos_readlink(const char* path, char* buf, size_t bufsize);

// 文件监视
int ainos_file_watch(const char* path, ainos_file_watch_cb callback, void* user_data);
```

### 11. 动态库加载 (Dynamic Library)

```c
// 头文件: <ainos/pal/dl.h>

int ainos_dl_open(ainos_dl_t* lib, const char* path, int flags);
int ainos_dl_close(ainos_dl_t lib);
void* ainos_dl_sym(ainos_dl_t lib, const char* symbol);
const char* ainos_dl_error(void);
```

### 12. 网络通信 (Network)

```c
// 头文件: <ainos/pal/net.h>

// Socket 操作
int ainos_socket_create(int domain, int type, int protocol);
int ainos_socket_close(int fd);
int ainos_socket_bind(int fd, const struct ainos_sockaddr* addr, socklen_t addrlen);
int ainos_socket_listen(int fd, int backlog);
int ainos_socket_accept(int fd, struct ainos_sockaddr* addr, socklen_t* addrlen);
int ainos_socket_connect(int fd, const struct ainos_sockaddr* addr, socklen_t addrlen);

// 数据收发
int64_t ainos_socket_send(int fd, const void* buf, uint64_t len, int flags);
int64_t ainos_socket_recv(int fd, void* buf, uint64_t len, int flags);
int64_t ainos_socket_sendto(int fd, const void* buf, uint64_t len, int flags,
                             const struct ainos_sockaddr* addr, socklen_t addrlen);
int64_t ainos_socket_recvfrom(int fd, void* buf, uint64_t len, int flags,
                               struct ainos_sockaddr* addr, socklen_t* addrlen);

// Socket 选项
int ainos_socket_setsockopt(int fd, int level, int optname, const void* optval, socklen_t optlen);
int ainos_socket_getsockopt(int fd, int level, int optname, void* optval, socklen_t* optlen);

// IO 多路复用
int ainos_poll_init(ainos_poll_t* poll);
int ainos_poll_add(ainos_poll_t poll, int fd, uint32_t events);
int ainos_poll_remove(ainos_poll_t poll, int fd);
int ainos_poll_wait(ainos_poll_t poll, struct ainos_poll_event* events, 
                     int max_events, int timeout_ms);

// 域名解析
int ainos_getaddrinfo(const char* node, const char* service,
                       const struct ainos_addrinfo* hints,
                       struct ainos_addrinfo** res);
void ainos_freeaddrinfo(struct ainos_addrinfo* res);
```

### 13. 时间管理 (Time)

```c
// 头文件: <ainos/pal/time.h>

// 获取当前时间
int ainos_clock_gettime(ainos_clockid_t clock_id, struct ainos_timespec* tp);
int ainos_clock_getres(ainos_clockid_t clock_id, struct ainos_timespec* res);

// 高精度计时
uint64_t ainos_time_now_ns(void);
uint64_t ainos_time_now_us(void);
uint64_t ainos_time_now_ms(void);

// 时间转换
int64_t ainos_time_to_epoch(const struct ainos_timespec* tp);
struct ainos_timespec ainos_time_from_epoch(int64_t epoch);

// 定时器
int ainos_timer_create(ainos_timer_t* timer);
int ainos_timer_set(ainos_timer_t timer, uint64_t interval_ms, int periodic);
int ainos_timer_cancel(ainos_timer_t timer);
int ainos_timer_destroy(ainos_timer_t timer);
int ainos_timer_wait(ainos_timer_t timer);
```

### 14. 字符串处理 (String)

```c
// 头文件: <ainos/pal/string.h>

size_t ainos_strlen(const char* s);
char* ainos_strcpy(char* dest, const char* src);
char* ainos_strncpy(char* dest, const char* src, size_t n);
char* ainos_strcat(char* dest, const char* src);
char* ainos_strncat(char* dest, const char* src, size_t n);
int ainos_strcmp(const char* s1, const char* s2);
int ainos_strncmp(const char* s1, const char* s2, size_t n);
char* ainos_strstr(const char* haystack, const char* needle);
char* ainos_strchr(const char* s, int c);
char* ainos_strrchr(const char* s, int c);
char* ainos_strdup(const char* s);
char* ainos_strndup(const char* s, size_t n);

// 字符串格式化
int ainos_snprintf(char* buf, size_t size, const char* fmt, ...);
int ainos_vsnprintf(char* buf, size_t size, const char* fmt, va_list args);

// 内存操作
void* ainos_memset(void* s, int c, size_t n);
void* ainos_memcpy(void* dest, const void* src, size_t n);
void* ainos_memmove(void* dest, const void* src, size_t n);
int ainos_memcmp(const void* s1, const void* s2, size_t n);
```

### 15. 数学函数 (Math)

```c
// 头文件: <ainos/pal/math.h>

// 基础数学
float ainos_sinf(float x);
double ainos_sin(double x);
float ainos_cosf(float x);
double ainos_cos(double x);
float ainos_tanf(float x);
double ainos_tan(double x);
float ainos_sqrtf(float x);
double ainos_sqrt(double x);
float ainos_expf(float x);
double ainos_exp(double x);
float ainos_logf(float x);
double ainos_log(double x);

// 向量运算
void ainos_vec3_add(float* result, const float* a, const float* b);
void ainos_vec3_sub(float* result, const float* a, const float* b);
void ainos_vec3_dot(float* result, const float* a, const float* b);
void ainos_vec3_cross(float* result, const float* a, const float* b);
void ainos_vec3_normalize(float* v);
void ainos_mat4_mul(float* result, const float* a, const float* b);
```

### 16. 随机数生成 (Random)

```c
// 头文件: <ainos/pal/random.h>

// 随机数填充
int ainos_random_bytes(void* buf, size_t len);

// 随机数生成
uint32_t ainos_random_u32(void);
uint64_t ainos_random_u64(void);
float ainos_random_float(void);
double ainos_random_double(void);

// 范围随机
int32_t ainos_random_range(int32_t min, int32_t max);

// 种子设置
void ainos_random_seed(uint64_t seed);
```

### 17. 日志系统 (Logging)

```c
// 头文件: <ainos/pal/log.h>

// 日志级别
#define AINOS_LOG_LEVEL_NONE    0
#define AINOS_LOG_LEVEL_ERROR   1
#define AINOS_LOG_LEVEL_WARN    2
#define AINOS_LOG_LEVEL_INFO    3
#define AINOS_LOG_LEVEL_DEBUG   4
#define AINOS_LOG_LEVEL_TRACE   5

// 日志函数
void ainos_log_set_level(int level);
int ainos_log_get_level(void);
void ainos_log_set_file(const char* path);
void ainos_log(int level, const char* file, int line, const char* func, 
                const char* fmt, ...);

// 便捷宏
#define AINOS_LOG_ERROR(fmt, ...)  ainos_log(AINOS_LOG_LEVEL_ERROR, __FILE__, __LINE__, __func__, fmt, ##__VA_ARGS__)
#define AINOS_LOG_WARN(fmt, ...)   ainos_log(AINOS_LOG_LEVEL_WARN, __FILE__, __LINE__, __func__, fmt, ##__VA_ARGS__)
#define AINOS_LOG_INFO(fmt, ...)   ainos_log(AINOS_LOG_LEVEL_INFO, __FILE__, __LINE__, __func__, fmt, ##__VA_ARGS__)
#define AINOS_LOG_DEBUG(fmt, ...)  ainos_log(AINOS_LOG_LEVEL_DEBUG, __FILE__, __LINE__, __func__, fmt, ##__VA_ARGS__)
#define AINOS_LOG_TRACE(fmt, ...)  ainos_log(AINOS_LOG_LEVEL_TRACE, __FILE__, __LINE__, __func__, fmt, ##__VA_ARGS__)
```

### 18. 断言和错误处理 (Assert)

```c
// 头文件: <ainos/pal/assert.h>

void ainos_assert_fail(const char* expr, const char* file, int line, const char* func);
#define AINOS_ASSERT(expr) \
    do { if (!(expr)) ainos_assert_fail(#expr, __FILE__, __LINE__, __func__); } while(0)

// 错误码
int ainos_errno_get(void);
void ainos_errno_set(int err);
const char* ainos_strerror(int errnum);
```

### 19. 环境变量 (Environment)

```c
// 头文件: <ainos/pal/env.h>

char* ainos_getenv(const char* name);
int ainos_setenv(const char* name, const char* value, int overwrite);
int ainos_unsetenv(const char* name);
int ainos_clearenv(void);
```

### 20. 进程管理 (Process)

```c
// 头文件: <ainos/pal/process.h>

int ainos_process_create(ainos_process_t* proc, const char* path, 
                          char* const argv[], char* const envp[]);
int ainos_process_wait(ainos_process_t proc, int* exit_code);
int ainos_process_kill(ainos_process_t proc, int sig);
int ainos_process_getpid(void);
int ainos_process_getppid(void);

// 进程间通信
int ainos_pipe_create(int pipefd[2]);
int ainos_pipe_close(int fd);
```

### 21. 共享内存 (Shared Memory)

```c
// 头文件: <ainos/pal/shm.h>

int ainos_shm_open(const char* name, int oflag, int mode);
int ainos_shm_unlink(const char* name);
int ainos_shm_get_size(int fd, uint64_t* size);
int ainos_shm_set_size(int fd, uint64_t size);
```

### 22. 信号处理 (Signal)

```c
// 头文件: <ainos/pal/signal.h>

typedef void (*ainos_signal_handler_t)(int signum);
int ainos_signal_set(int signum, ainos_signal_handler_t handler);
int ainos_signal_restore(int signum);
int ainos_signal_send(ainos_pid_t pid, int signum);
int ainos_signal_self(int signum);
int ainos_signal_mask(int how, const ainos_sigset_t* set, ainos_sigset_t* oldset);
int ainos_signal_pending(ainos_sigset_t* set);
int ainos_signal_wait(const ainos_sigset_t* set, int* sig);
```

### 23. CPU 信息 (CPU Info)

```c
// 头文件: <ainos/pal/cpu.h>

int ainos_cpu_count(void);
int ainos_cpu_online_count(void);
int64_t ainos_cpu_freq_current(void);
int64_t ainos_cpu_freq_max(void);
int ainos_cpu_has_feature(const char* feature);
void ainos_cpu_get_cache_info(struct ainos_cpu_cache_info* info);
int ainos_cpu_get_info(struct ainos_cpu_info* info);
```

### 24. 端序转换 (Endian)

```c
// 头文件: <ainos/pal/endian.h>

int ainos_is_little_endian(void);
int ainos_is_big_endian(void);

uint16_t ainos_htobe16(uint16_t host);
uint16_t ainos_htole16(uint16_t host);
uint16_t ainos_be16toh(uint16_t be);
uint16_t ainos_le16toh(uint16_t le);

uint32_t ainos_htobe32(uint32_t host);
uint32_t ainos_htole32(uint32_t host);
uint32_t ainos_be32toh(uint32_t be);
uint32_t ainos_le32toh(uint32_t le);

uint64_t ainos_htobe64(uint64_t host);
uint64_t ainos_htole64(uint64_t host);
uint64_t ainos_be64toh(uint64_t be);
uint64_t ainos_le64toh(uint64_t le);
```

### 25. 哈希和校验 (Hash)

```c
// 头文件: <ainos/pal/hash.h>

// CRC32
uint32_t ainos_crc32(const void* data, size_t len);
uint32_t ainos_crc32_combine(uint32_t crc1, uint32_t crc2, size_t len2);

// MD5
int ainos_md5_init(ainos_md5_ctx_t* ctx);
int ainos_md5_update(ainos_md5_ctx_t* ctx, const void* data, size_t len);
int ainos_md5_final(ainos_md5_ctx_t* ctx, uint8_t digest[16]);

// SHA256
int ainos_sha256_init(ainos_sha256_ctx_t* ctx);
int ainos_sha256_update(ainos_sha256_ctx_t* ctx, const void* data, size_t len);
int ainos_sha256_final(ainos_sha256_ctx_t* ctx, uint8_t digest[32]);

// XXHash
uint64_t ainos_xxhash64(const void* data, size_t len, uint64_t seed);
```

### 26.  UUID 生成 (UUID)

```c
// 头文件: <ainos/pal/uuid.h>

typedef struct {
    uint8_t data[16];
} ainos_uuid_t;

int ainos_uuid_generate(ainos_uuid_t* uuid);
int ainos_uuid_generate_random(ainos_uuid_t* uuid);
int ainos_uuid_parse(const char* str, ainos_uuid_t* uuid);
void ainos_uuid_unparse(const ainos_uuid_t* uuid, char* str);
int ainos_uuid_compare(const ainos_uuid_t* a, const ainos_uuid_t* b);
```

### 27. 压缩 (Compression)

```c
// 头文件: <ainos/pal/compress.h>

// Zlib 压缩
int ainos_compress_zlib(const void* src, size_t src_len, 
                         void* dst, size_t* dst_len, int level);
int ainos_uncompress_zlib(const void* src, size_t src_len, 
                           void* dst, size_t* dst_len);
```

### 28. 终端控制 (Terminal)

```c
// 头文件: <ainos/pal/tty.h>

int ainos_tty_isatty(int fd);
int ainos_tty_get_size(int* cols, int* rows);
int ainos_tty_raw_mode(int fd);
int ainos_tty_normal_mode(int fd);
int ainos_tty_color_supported(void);
```

### 29. 权限控制 (Permissions)

```c
// 头文件: <ainos/pal/perm.h>

int ainos_perm_check(const char* resource, int perm_type);
int ainos_perm_request(const char* resource, int perm_type);
int ainos_perm_revoke(const char* resource, int perm_type);
```

### 30. 电源管理 (Power)

```c
// 头文件: <ainos/pal/power.h>

int ainos_power_get_battery_level(int* percent);
int ainos_power_is_charging(void);
int ainos_power_get_temp(double* temp_celsius);
int ainos_power_throttle_if_needed(void);
```

### 31. 硬件监控 (Hardware Monitor)

```c
// 头文件: <ainos/pal/hwmon.h>

int ainos_hwmon_get_cpu_temp(double* temp);
int ainos_hwmon_get_gpu_temp(double* temp);
int ainos_hwmon_get_fan_speed(int* rpm);
int ainos_hwmon_get_memory_temp(double* temp);
```

## 平台检测宏

```c
// 头文件: <ainos/pal/detect.h>

// 操作系统检测
#define AINOS_PLATFORM_WINDOWS   1  // Windows 平台
#define AINOS_PLATFORM_LINUX     2  // Linux 平台
#define AINOS_PLATFORM_MACOS     3  // macOS 平台
#define AINOS_PLATFORM_BSD       4  // BSD 平台
#define AINOS_PLATFORM_ANDROID   5  // Android 平台

// 架构检测
#define AINOS_ARCH_X86_64        1  // x86-64 架构
#define AINOS_ARCH_ARM64         2  // ARM64 架构
#define AINOS_ARCH_ARM32         3  // ARM32 架构
#define AINOS_ARCH_RISCV64       4  // RISC-V 64 架构
#define AINOS_ARCH_WASM          5  // WebAssembly 架构

// 检测宏
#if defined(_WIN32) || defined(_WIN64)
    #define AINOS_PLATFORM AINOS_PLATFORM_WINDOWS
#elif defined(__APPLE__) && defined(__MACH__)
    #define AINOS_PLATFORM AINOS_PLATFORM_MACOS
#elif defined(__ANDROID__)
    #define AINOS_PLATFORM AINOS_PLATFORM_ANDROID
#elif defined(__linux__)
    #define AINOS_PLATFORM AINOS_PLATFORM_LINUX
#elif defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__)
    #define AINOS_PLATFORM AINOS_PLATFORM_BSD
#endif

// 架构检测宏
#if defined(__x86_64__) || defined(_M_X64)
    #define AINOS_ARCH AINOS_ARCH_X86_64
#elif defined(__aarch64__) || defined(_M_ARM64)
    #define AINOS_ARCH AINOS_ARCH_ARM64
#elif defined(__ARM_ARCH) || defined(_M_ARM)
    #define AINOS_ARCH AINOS_ARCH_ARM32
#elif defined(__riscv) && __riscv_xlen == 64
    #define AINOS_ARCH AINOS_ARCH_RISCV64
#elif defined(__wasm__)
    #define AINOS_ARCH AINOS_ARCH_WASM
#endif
```

## 各平台实现差异

### 线程实现差异

| 特性 | Windows | Linux | macOS |
|------|---------|-------|-------|
| 线程创建 | CreateThread | pthread_create | pthread_create |
| 线程属性 | 无原生支持 | pthread_attr_t | pthread_attr_t |
| 线程优先级 | SetThreadPriority | pthread_setschedparam | pthread_setschedparam |
| CPU 亲和性 | SetThreadAffinityMask | pthread_setaffinity_np | thread_policy_set |
| TLS | TlsAlloc | pthread_key_create | pthread_key_create |
| 线程 ID | GetCurrentThreadId | gettid | pthread_threadid_np |

### 互斥锁实现差异

| 特性 | Windows | Linux | macOS |
|------|---------|-------|-------|
| 互斥锁 | CRITICAL_SECTION/SRWLock | pthread_mutex_t | pthread_mutex_t |
| 递归锁 | 默认递归 | PTHREAD_MUTEX_RECURSIVE | PTHREAD_MUTEX_RECURSIVE |
| 读写锁 | SRWLOCK | pthread_rwlock_t | pthread_rwlock_t |
| 超时锁 | SleepConditionVariableCS | pthread_mutex_timedlock | pthread_mutex_timedlock |

### 内存管理实现差异

| 特性 | Windows | Linux | macOS |
|------|---------|-------|-------|
| 堆内存 | HeapAlloc | malloc | malloc |
| 大页内存 | VirtualAlloc + MEM_LARGE_PAGES | mmap + MAP_HUGETLB | mmap + MAP_ALIGNED |
| 内存映射 | CreateFileMapping | mmap | mmap |
| 内存锁定 | VirtualLock | mlock | mlock |

### 文件系统实现差异

| 特性 | Windows | Linux | macOS |
|------|---------|-------|-------|
| 路径分隔符 | \ | / | / |
| 路径最大长度 | 260 (MAX_PATH) | 4096 | 1024 |
| 文件锁 | LockFileEx | flock/flock | flock |
| 文件监视 | ReadDirectoryChangesW | inotify | FSEvents |
| 符号链接 | 需管理员权限 | symlink() | symlink() |

### 网络实现差异

| 特性 | Windows | Linux | macOS |
|------|---------|-------|-------|
| Socket API | Winsock2 | POSIX Socket | POSIX Socket |
| 初始化 | WSAStartup | 无需初始化 | 无需初始化 |
| IO 多路复用 | IOCP/WSAEventSelect | epoll | kqueue |
| 异步 IO | Overlapped I/O | AIO | dispatch |

## 移植指南

### 添加新平台支持

1. **创建平台目录**: 在 `src/pal/` 下创建 `platform_name/` 目录
2. **实现平台检测**: 在 `include/ainos/pal/detect.h` 中添加新的平台检测宏
3. **实现所有 API 组**: 每个 API 组至少需要实现以下文件：
   - `thread_platform.c`
   - `mutex_platform.c`
   - `memory_platform.c`
   - `fs_platform.c`
   - `net_platform.c`
   - `time_platform.c`
   - 其他所需文件

4. **更新构建系统**: 在 CMakeLists.txt 中添加新的平台构建目标

### 实现检查清单

```c
// 每个 API 组实现后验证模板
#include <ainos/pal/all.h>

void verify_pal_implementation(void) {
    // 1. 线程
    ainos_thread_t thread;
    assert(ainos_thread_create(&thread, test_func, NULL, NULL) == 0);
    assert(ainos_thread_join(thread, NULL) == 0);
    
    // 2. 互斥锁
    ainos_mutex_t mutex;
    assert(ainos_mutex_init(&mutex, NULL) == 0);
    assert(ainos_mutex_lock(&mutex) == 0);
    assert(ainos_mutex_unlock(&mutex) == 0);
    assert(ainos_mutex_destroy(&mutex) == 0);
    
    // 3. 内存
    void* ptr = ainos_malloc(1024);
    assert(ptr != NULL);
    ainos_free(ptr);
    
    // 4. 文件系统
    ainos_file_t file;
    assert(ainos_file_open(&file, "/tmp/test.txt", 
           AINOS_O_CREAT | AINOS_O_WRONLY, 0644) == 0);
    assert(ainos_file_close(file) == 0);
    assert(ainos_unlink("/tmp/test.txt") == 0);
    
    // 5. 时间
    uint64_t start = ainos_time_now_ns();
    ainos_thread_sleep(10);
    uint64_t elapsed = ainos_time_now_ns() - start;
    assert(elapsed >= 10 * 1000000);
    
    printf("所有平台抽象层 API 验证通过！\n");
}
```

### 性能基准

```c
// 平台抽象层性能基准测试
void pal_benchmark(void) {
    uint64_t start, elapsed;
    const int ITERATIONS = 1000000;
    
    // 线程创建/销毁性能
    start = ainos_time_now_ns();
    for (int i = 0; i < 1000; i++) {
        ainos_thread_t t;
        ainos_thread_create(&t, empty_func, NULL, NULL);
        ainos_thread_join(t, NULL);
    }
    elapsed = ainos_time_now_ns() - start;
    printf("线程创建/销毁: %lu ns/op\n", elapsed / 1000);
    
    // 互斥锁性能
    ainos_mutex_t m;
    ainos_mutex_init(&m, NULL);
    start = ainos_time_now_ns();
    for (int i = 0; i < ITERATIONS; i++) {
        ainos_mutex_lock(&m);
        ainos_mutex_unlock(&m);
    }
    elapsed = ainos_time_now_ns() - start;
    printf("互斥锁加锁/解锁: %lu ns/op\n", elapsed / ITERATIONS);
    ainos_mutex_destroy(&m);
    
    // 内存分配性能
    start = ainos_time_now_ns();
    for (int i = 0; i < 100000; i++) {
        void* p = ainos_malloc(64);
        ainos_free(p);
    }
    elapsed = ainos_time_now_ns() - start;
    printf("内存分配/释放: %lu ns/op\n", elapsed / 100000);
    
    // 文件 I/O 性能
    // 写入
    ainos_file_t f;
    ainos_file_open(&f, "/tmp/bench.tmp", AINOS_O_CREAT | AINOS_O_WRONLY, 0644);
    char buf[4096];
    ainos_memset(buf, 0x41, sizeof(buf));
    start = ainos_time_now_ns();
    for (int i = 0; i < 10000; i++) {
        ainos_file_write(f, buf, sizeof(buf));
    }
    elapsed = ainos_time_now_ns() - start;
    printf("文件写入: %lu MB/s\n", (10000ULL * sizeof(buf) * 1000000000ULL) / (elapsed * 1024 * 1024));
    ainos_file_close(f);
    ainos_unlink("/tmp/bench.tmp");
}
```

## 最佳实践

1. **不要直接使用平台 API**: 始终通过 PAL 接口操作，确保代码可移植性
2. **错误检查**: 所有 PAL 函数返回 int 错误码，始终检查返回值
3. **资源管理**: 使用 RAII 模式或明确的 alloc/free 配对
4. **线程安全**: PAL 本身保证线程安全，但上层使用仍需考虑同步
5. **性能关键路径**: 对于性能敏感的路径，可以使用平台特定的优化，但需提供 fallback
6. **内存对齐**: AI 工作负载对内存对齐敏感，使用 ainos_aligned_alloc
7. **大页内存**: 对 KV 缓存等大块内存使用大页分配
8. **CPU 亲和性**: 将推理线程绑定到特定核心以提高缓存命中率