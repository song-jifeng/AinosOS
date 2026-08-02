// SPDX-License-Identifier: GPL-2.0
// Ainos OS - ai-proc-bridge: 内核 ↔ ai-daemon 桥接器
// 运行在用户态，通过 /dev/ainos-proc 与内核通信
// 通过 TCP 与 ai-daemon (127.0.0.1:9500) 通信
//
// 职责:
//   1. 阻塞等待内核的 AI 请求
//   2. 转发给 ai-daemon 处理
//   3. 将结果写回内核
//   4. 处理重试/超时/重连
//
// 编译:
//   gcc -O2 -Wall -o ai-proc-bridge ai-proc-bridge.c
//
// 运行:
//   ./ai-proc-bridge              # 前台
//   ./ai-proc-bridge --daemon     # 后台守护进程

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdarg.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <time.h>

/* 内核 IOCTL 定义 (与 proc_ai.h 保持一致) */
#define AI_PROC_IOC_MAGIC  'P'
#define AI_PROC_GET_REQUEST   _IOR(AI_PROC_IOC_MAGIC, 1, struct ai_proc_request)
#define AI_PROC_SEND_RESPONSE _IOW(AI_PROC_IOC_MAGIC, 2, struct ai_proc_response)

/* 文件类型 */
enum ai_proc_file_id {
    AI_PROC_FILE_STATUS = 0,
    AI_PROC_FILE_INFER  = 1,
    AI_PROC_FILE_EMBED  = 2,
    AI_PROC_FILE_CHAT   = 3,
    AI_PROC_FILE_MODELS = 4,
    AI_PROC_FILE_CONFIG = 5,
    AI_PROC_FILE_STATS  = 6,
};

/* 请求结构 (与内核一致) */
struct ai_proc_request {
    uint32_t id;
    uint32_t file_id;
    uint32_t session_id;
    uint32_t status;
    char     data[4096];
    uint32_t len;
    uint32_t flags;
    struct timespec submitted;
};

/* 响应结构 (与内核一致) */
struct ai_proc_response {
    uint32_t req_id;
    uint32_t status;
    char     data[65536];
    uint32_t len;
    char     source[16];
    uint32_t tokens;
    uint64_t inference_ms;
};

/* ================================================================
 * 配置
 * ================================================================ */

#define DEVICE_PATH      "/dev/ainos-proc"
#define DAEMON_ADDR      "127.0.0.1"
#define DAEMON_PORT      9500
#define MAX_RETRIES      3
#define TIMEOUT_SEC      30
#define RECONNECT_DELAY  2  /* 重连延迟 (秒) */
#define PID_FILE         "/var/run/ai-proc-bridge.pid"
#define LOG_FILE         "/var/log/ainos/ai-proc-bridge.log"

static int g_daemon_mode = 0;
static int g_running = 1;
static int g_dev_fd = -1;
static int g_daemon_fd = -1;
static uint64_t g_requests_forwarded = 0;
static uint64_t g_requests_success = 0;
static uint64_t g_requests_failed = 0;
static uint64_t g_requests_retried = 0;

/* ================================================================
 * 日志
 * ================================================================ */

static FILE *g_log_fp = NULL;

static void log_msg(const char *fmt, ...)
{
    va_list args;
    char buf[4096];
    time_t now;
    struct tm *tm_info;

    time(&now);
    tm_info = localtime(&now);

    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    /* 标准输出 */
    if (!g_daemon_mode) {
        printf("[%02d:%02d:%02d] %s\n",
               tm_info->tm_hour, tm_info->tm_min, tm_info->tm_sec, buf);
        fflush(stdout);
    }

    /* 日志文件 */
    if (g_log_fp) {
        fprintf(g_log_fp, "[%04d-%02d-%02d %02d:%02d:%02d] %s\n",
                tm_info->tm_year + 1900, tm_info->tm_mon + 1, tm_info->tm_mday,
                tm_info->tm_hour, tm_info->tm_min, tm_info->tm_sec, buf);
        fflush(g_log_fp);
    }
}

/* ================================================================
 * 信号处理
 * ================================================================ */

static void signal_handler(int sig)
{
    switch (sig) {
    case SIGINT:
    case SIGTERM:
        log_msg("signal %d received, shutting down", sig);
        g_running = 0;
        break;
    case SIGHUP:
        log_msg("SIGHUP received, reconnecting to daemon");
        /* 触发重连 */
        if (g_daemon_fd >= 0) {
            close(g_daemon_fd);
            g_daemon_fd = -1;
        }
        break;
    }
}

static void setup_signals(void)
{
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = signal_handler;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    /* 忽略 SIGPIPE (write 到关闭的 socket 时不崩溃) */
    signal(SIGPIPE, SIG_IGN);
}

/* ================================================================
 * Daemon 化
 * ================================================================ */

static void daemonize(void)
{
    pid_t pid;

    pid = fork();
    if (pid < 0) {
        fprintf(stderr, "fork failed: %s\n", strerror(errno));
        exit(1);
    }
    if (pid > 0) {
        /* 父进程退出 */
        fprintf(stdout, "ai-proc-bridge started (pid=%d)\n", pid);
        exit(0);
    }

    /* 子进程 */
    setsid();

    /* 关闭标准文件描述符 */
    close(0);
    close(1);
    close(2);

    /* 重定向到 /dev/null */
    open("/dev/null", O_RDONLY);  /* stdin */
    open("/dev/null", O_WRONLY);  /* stdout */
    open("/dev/null", O_WRONLY);  /* stderr */

    /* 写 PID 文件 */
    FILE *pid_fp = fopen(PID_FILE, "w");
    if (pid_fp) {
        fprintf(pid_fp, "%d\n", getpid());
        fclose(pid_fp);
    }

    g_daemon_mode = 1;
}

/* ================================================================
 * 设备操作
 * ================================================================ */

static int open_device(void)
{
    int fd = open(DEVICE_PATH, O_RDWR);
    if (fd < 0) {
        log_msg("failed to open %s: %s", DEVICE_PATH, strerror(errno));
        return -1;
    }
    log_msg("opened %s (fd=%d)", DEVICE_PATH, fd);
    return fd;
}

static int get_request(int dev_fd, struct ai_proc_request *req)
{
    memset(req, 0, sizeof(*req));

    /* 阻塞等待请求到来 */
    struct pollfd pfd = {
        .fd = dev_fd,
        .events = POLLIN,
    };

    int ret = poll(&pfd, 1, 1000); /* 1 秒超时用于检查 g_running */
    if (ret < 0) {
        if (errno == EINTR) return -1;
        log_msg("poll error: %s", strerror(errno));
        return -1;
    }
    if (ret == 0) return -1; /* 超时 */

    if (!(pfd.revents & POLLIN)) return -1;

    ret = ioctl(dev_fd, AI_PROC_GET_REQUEST, req);
    if (ret < 0) {
        if (errno == EAGAIN) return -1;
        log_msg("ioctl GET_REQUEST error: %s", strerror(errno));
        return -1;
    }

    return 0;
}

static int send_response(int dev_fd, struct ai_proc_response *resp)
{
    int ret = ioctl(dev_fd, AI_PROC_SEND_RESPONSE, resp);
    if (ret < 0) {
        log_msg("ioctl SEND_RESPONSE error: %s", strerror(errno));
        return -1;
    }
    return 0;
}

/* ================================================================
 * ai-daemon TCP 通信
 * ================================================================ */

static int connect_daemon(void)
{
    int fd;
    struct sockaddr_in addr;
    struct hostent *host;
    int ret;

    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        log_msg("socket error: %s", strerror(errno));
        return -1;
    }

    /* 设置超时 */
    struct timeval tv = {
        .tv_sec = TIMEOUT_SEC,
        .tv_usec = 0,
    };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(DAEMON_PORT);

    host = gethostbyname(DAEMON_ADDR);
    if (host) {
        memcpy(&addr.sin_addr, host->h_addr, host->h_length);
    } else {
        addr.sin_addr.s_addr = inet_addr(DAEMON_ADDR);
    }

    ret = connect(fd, (struct sockaddr *)&addr, sizeof(addr));
    if (ret < 0) {
        log_msg("connect to %s:%d failed: %s",
                DAEMON_ADDR, DAEMON_PORT, strerror(errno));
        close(fd);
        return -1;
    }

    log_msg("connected to ai-daemon at %s:%d", DAEMON_ADDR, DAEMON_PORT);
    return fd;
}

/* 构建 JSON 请求 (与 ai-daemon IPC 协议兼容) */
static int build_json_request(const struct ai_proc_request *req,
                              char *json, size_t json_size)
{
    /* 转义 prompt 中的特殊字符 */
    char *escaped = malloc(req->len * 2 + 1);
    if (!escaped) return -1;

    size_t j = 0;
    for (uint32_t i = 0; i < req->len && i < 4096; i++) {
        unsigned char c = req->data[i];
        if (c == '"' || c == '\\') {
            escaped[j++] = '\\';
            escaped[j++] = c;
        } else if (c == '\n') {
            escaped[j++] = '\\';
            escaped[j++] = 'n';
        } else if (c == '\r') {
            escaped[j++] = '\\';
            escaped[j++] = 'r';
        } else if (c == '\t') {
            escaped[j++] = '\\';
            escaped[j++] = 't';
        } else if (c < 0x20) {
            j += snprintf(escaped + j, 7, "\\u%04x", c);
        } else {
            escaped[j++] = c;
        }
    }
    escaped[j] = '\0';

    const char *type_str;
    switch (req->file_id) {
    case AI_PROC_FILE_INFER:  type_str = "Inference";  break;
    case AI_PROC_FILE_EMBED:  type_str = "Inference";  break; /* model=embed */
    case AI_PROC_FILE_CHAT:   type_str = "Inference";  break;
    default:                  type_str = "Inference";  break;
    }

    const char *model_str;
    switch (req->file_id) {
    case AI_PROC_FILE_EMBED:  model_str = "embed";    break;
    default:                  model_str = "default";   break;
    }

    int n = snprintf(json, json_size,
        "{\"type\":\"%s\",\"model\":\"%s\",\"prompt\":\"%s\""
        ",\"temperature\":0.7,\"max_tokens\":1024}",
        type_str, model_str, escaped);

    free(escaped);

    if (n < 0 || (size_t)n >= json_size) {
        log_msg("JSON buffer too small (%d < %d)", (int)json_size, n);
        return -1;
    }

    return n;
}

/* 解析 daemon 响应 */
static int parse_daemon_response(const char *response,
                                 struct ai_proc_response *resp)
{
    const char *output_start, *output_end;
    const char *tokens_start, *ms_start, *source_start;

    resp->status = 0;
    resp->source[0] = '\0';
    resp->tokens = 0;
    resp->inference_ms = 0;

    /* 提取 output */
    output_start = strstr(response, "\"output\"");
    if (output_start) {
        output_start = strchr(output_start, ':');
        if (output_start) {
            output_start++;
            while (*output_start == ' ' || *output_start == '\t') output_start++;
            if (*output_start == '"') {
                output_start++;
                output_end = strchr(output_start, '"');
                if (output_end) {
                    size_t out_len = output_end - output_start;
                    if (out_len > sizeof(resp->data) - 1)
                        out_len = sizeof(resp->data) - 1;
                    memcpy(resp->data, output_start, out_len);
                    resp->data[out_len] = '\0';
                    resp->len = out_len;
                }
            }
        }
    }

    /* 提取 source */
    source_start = strstr(response, "\"source\"");
    if (source_start) {
        source_start = strchr(source_start, ':');
        if (source_start) {
            source_start++;
            while (*source_start == ' ' || *source_start == '\t') source_start++;
            if (*source_start == '"') {
                source_start++;
                const char *end = strchr(source_start, '"');
                if (end) {
                    size_t slen = end - source_start;
                    if (slen > sizeof(resp->source) - 1)
                        slen = sizeof(resp->source) - 1;
                    memcpy(resp->source, source_start, slen);
                    resp->source[slen] = '\0';
                }
            }
        }
    }

    return 0;
}

/* 转发请求到 daemon */
static int forward_to_daemon(int daemon_fd,
                             const struct ai_proc_request *req,
                             struct ai_proc_response *resp)
{
    char json[8192];
    int json_len;
    char recv_buf[65536];
    int retry;

    resp->req_id = req->id;

    json_len = build_json_request(req, json, sizeof(json));
    if (json_len < 0) {
        resp->status = 1;
        snprintf(resp->data, sizeof(resp->data),
                 "JSON build error");
        return -1;
    }

    for (retry = 0; retry < MAX_RETRIES; retry++) {
        /* 发送请求 */
        ssize_t sent = write(daemon_fd, json, json_len);
        if (sent < 0) {
            log_msg("write error (retry %d/3): %s",
                    retry + 1, strerror(errno));
            if (errno == EPIPE) {
                /* 连接断开，重连 */
                close(daemon_fd);
                g_daemon_fd = -1;
                return -1;
            }
            continue;
        }

        /* 发送换行符 (消息结束标记) */
        char newline = '\n';
        sent = write(daemon_fd, &newline, 1);
        if (sent < 0) {
            log_msg("write newline error (retry %d/3): %s",
                    retry + 1, strerror(errno));
            continue;
        }

        /* 读取响应 */
        ssize_t total = 0;
        ssize_t n;
        int found_newline = 0;

        while (total < (ssize_t)sizeof(recv_buf) - 1) {
            n = read(daemon_fd, recv_buf + total, 1);
            if (n <= 0) {
                if (errno == EAGAIN || errno == EINTR) continue;
                break;
            }
            if (recv_buf[total] == '\n') {
                found_newline = 1;
                break;
            }
            total++;
        }

        recv_buf[total] = '\0';

        if (found_newline && total > 0) {
            parse_daemon_response(recv_buf, resp);
            g_requests_success++;
            return 0;
        }

        /* 超时或错误，重试 */
        g_requests_retried++;
        log_msg("request timeout/error (retry %d/3)", retry + 1);

        if (retry < MAX_RETRIES - 1) {
            sleep(1);
        }
    }

    /* 所有重试失败 */
    resp->status = 1;
    snprintf(resp->data, sizeof(resp->data),
             "Bridge: request failed after %d retries (timeout=%ds)",
             MAX_RETRIES, TIMEOUT_SEC);
    g_requests_failed++;
    log_msg("request %u failed after %d retries", req->id, MAX_RETRIES);
    return -1;
}

/* ================================================================
 * 主循环
 * ================================================================ */

static int run_bridge(void)
{
    struct ai_proc_request req;
    struct ai_proc_response resp;

    log_msg("ai-proc-bridge started (pid=%d)", getpid());

    /* 打开设备 */
    g_dev_fd = open_device();
    if (g_dev_fd < 0) {
        log_msg("failed to open device, aborting");
        return 1;
    }

    while (g_running) {
        /* 检查 daemon 连接 */
        if (g_daemon_fd < 0) {
            log_msg("connecting to ai-daemon...");
            g_daemon_fd = connect_daemon();
            if (g_daemon_fd < 0) {
                log_msg("cannot connect to ai-daemon, retry in %ds",
                        RECONNECT_DELAY);
                sleep(RECONNECT_DELAY);
                continue;
            }
        }

        /* 获取内核请求 (阻塞) */
        int ret = get_request(g_dev_fd, &req);
        if (ret < 0) {
            if (!g_running) break;
            continue;
        }

        g_requests_forwarded++;

        const char *file_names[] = {
            "status", "infer", "embed", "chat", "models", "config", "stats"
        };
        const char *fname = (req.file_id < 7) ? file_names[req.file_id] : "?";

        log_msg("request #%u [%s] len=%u session=%u",
                req.id, fname, req.len, req.session_id);

        /* 转发到 daemon */
        memset(&resp, 0, sizeof(resp));
        resp.req_id = req.id;

        if (forward_to_daemon(g_daemon_fd, &req, &resp) == 0) {
            log_msg("response #%u: len=%u source=%s tokens=%u",
                    req.id, resp.len, resp.source, resp.tokens);
        } else {
            log_msg("response #%u: FAILED", req.id);
        }

        /* 写回内核 */
        ret = send_response(g_dev_fd, &resp);
        if (ret < 0) {
            log_msg("failed to send response back to kernel");
        }
    }

    /* 清理 */
    if (g_dev_fd >= 0) close(g_dev_fd);
    if (g_daemon_fd >= 0) close(g_daemon_fd);

    log_msg("ai-proc-bridge stopped");
    log_msg("stats: forwarded=%lu success=%lu failed=%lu retried=%lu",
            g_requests_forwarded, g_requests_success,
            g_requests_failed, g_requests_retried);

    return 0;
}

/* ================================================================
 * 入口
 * ================================================================ */

int main(int argc, char *argv[])
{
    int opt;

    while ((opt = getopt(argc, argv, "dh")) != -1) {
        switch (opt) {
        case 'd':
            g_daemon_mode = 1;
            break;
        case 'h':
            printf("Usage: %s [-d] [-h]\n", argv[0]);
            printf("  -d    Run as daemon\n");
            printf("  -h    Show this help\n");
            return 0;
        }
    }

    /* 确保日志目录存在 */
    mkdir("/var/log/ainos", 0755);

    /* 打开日志文件 */
    g_log_fp = fopen(LOG_FILE, "a");
    if (!g_log_fp) {
        fprintf(stderr, "warning: cannot open log file %s\n", LOG_FILE);
    }

    /* 设置信号处理 */
    setup_signals();

    /* Daemon 化 */
    if (g_daemon_mode) {
        daemonize();
        /* 重新打开日志 (daemon 化后已关闭 stdout/stderr) */
        g_log_fp = fopen(LOG_FILE, "a");
    }

    int ret = run_bridge();

    if (g_log_fp) fclose(g_log_fp);

    /* 清理 PID 文件 */
    if (g_daemon_mode) {
        unlink(PID_FILE);
    }

    return ret;
}