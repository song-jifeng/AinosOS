// Ainos OS - AI 应用 SDK (libainos)
// 用户空间应用的 AI 能力接口库
// 支持 Windows 和 Linux 双平台
//
// 编译 (Windows):
//   gcc -shared -o libainos.dll libainos.c -lws2_32
//   gcc -c -o libainos.o libainos.c -lws2_32
//
// 编译 (Linux):
//   gcc -shared -fPIC -o libainos.so libainos.c -lpthread
//
// 使用:
//   #include <ainos/ainos.h>
//   gcc myapp.c -lainos -o myapp

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>

#ifdef _WIN32
#include <winsock2.h>
#include <windows.h>
#define close closesocket
typedef int socklen_t;
typedef SOCKET socket_t;
#define INVALID_SOCKET_VALUE INVALID_SOCKET
#else
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <pthread.h>
#include <netinet/in.h>
#include <arpa/inet.h>
typedef int socket_t;
#define INVALID_SOCKET_VALUE (-1)
#endif

#ifdef __cplusplus
extern "C" {
#endif

#include "ainos.h"

/* SDK 上下文结构 */
struct ainos_ctx {
    char server_addr[256];
    int port;
    socket_t sock;
    int connected;
    int use_unix_socket; /* 0=TCP, 1=Unix Domain Socket */
};

/* 内部函数声明 */
static int tcp_connect(ainos_ctx* ctx);
static int send_request(ainos_ctx* ctx, const char* json_request);
static char* recv_response(ainos_ctx* ctx);
static char* json_escape(const char* str);
static ainos_resp* parse_response(const char* json);

/* 初始化 SDK */
ainos_ctx* ainos_init(const char* server_addr) {
    ainos_ctx* ctx = (ainos_ctx*)calloc(1, sizeof(ainos_ctx));
    if (!ctx) return NULL;

    ctx->sock = INVALID_SOCKET_VALUE;
    ctx->connected = 0;
    ctx->use_unix_socket = 0;

    if (!server_addr || strlen(server_addr) >= sizeof(ctx->server_addr)) {
        free(ctx);
        return NULL;
    }

    strncpy(ctx->server_addr, server_addr, sizeof(ctx->server_addr) - 1);

    /* 解析地址: 检测是否为 "host:port" 格式 */
    char* colon = strchr(ctx->server_addr, ':');
    if (colon) {
        ctx->port = atoi(colon + 1);
        *colon = '\0';
        ctx->use_unix_socket = 0;
    } else {
        ctx->port = 0;
        ctx->use_unix_socket = 1;
    }

#ifdef _WIN32
    /* Windows 上强制使用 TCP */
    if (ctx->use_unix_socket) {
        ctx->use_unix_socket = 0;
        strncpy(ctx->server_addr, "127.0.0.1", sizeof(ctx->server_addr) - 1);
        ctx->port = 9500;
    }
#endif

    return ctx;
}

/* 连接 AI 守护进程 */
int ainos_connect(ainos_ctx* ctx) {
    if (!ctx) return AINOS_ERR_INVALID_PARAM;

#ifdef _WIN32
    /* Windows: 初始化 Winsock */
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        return AINOS_ERR_INTERNAL;
    }
#endif

    if (ctx->use_unix_socket) {
#ifndef _WIN32
        /* Unix Domain Socket */
        ctx->sock = socket(AF_UNIX, SOCK_STREAM, 0);
        if (ctx->sock == INVALID_SOCKET_VALUE) {
            return AINOS_ERR_CONNECT;
        }

        struct sockaddr_un addr;
        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        strncpy(addr.sun_path, ctx->server_addr, sizeof(addr.sun_path) - 1);

        if (connect(ctx->sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
            close(ctx->sock);
            ctx->sock = INVALID_SOCKET_VALUE;
            return AINOS_ERR_CONNECT;
        }
        ctx->connected = 1;
        return AINOS_OK;
#else
        return AINOS_ERR_CONNECT;
#endif
    } else {
        return tcp_connect(ctx);
    }
}

/* TCP 连接 */
static int tcp_connect(ainos_ctx* ctx) {
    ctx->sock = socket(AF_INET, SOCK_STREAM, 0);
    if (ctx->sock == INVALID_SOCKET_VALUE) {
        return AINOS_ERR_CONNECT;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(ctx->port);
    addr.sin_addr.s_addr = inet_addr(ctx->server_addr);

    if (addr.sin_addr.s_addr == INADDR_NONE) {
        /* 尝试 DNS 解析 */
        struct hostent* host = gethostbyname(ctx->server_addr);
        if (!host) {
            close(ctx->sock);
            ctx->sock = INVALID_SOCKET_VALUE;
            return AINOS_ERR_CONNECT;
        }
        memcpy(&addr.sin_addr, host->h_addr, host->h_length);
    }

    if (connect(ctx->sock, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(ctx->sock);
        ctx->sock = INVALID_SOCKET_VALUE;
        return AINOS_ERR_CONNECT;
    }

    ctx->connected = 1;
    return AINOS_OK;
}

/* JSON 字符串转义 */
static char* json_escape(const char* str) {
    if (!str) return strdup("");

    size_t len = strlen(str);
    /* 预估最大长度: 每个字符可能变成 \uXXXX 格式 */
    char* result = (char*)malloc(len * 6 + 1);
    if (!result) return NULL;

    size_t pos = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = str[i];
        switch (c) {
            case '"':  result[pos++] = '\\'; result[pos++] = '"';  break;
            case '\\': result[pos++] = '\\'; result[pos++] = '\\'; break;
            case '\n': result[pos++] = '\\'; result[pos++] = 'n';  break;
            case '\r': result[pos++] = '\\'; result[pos++] = 'r';  break;
            case '\t': result[pos++] = '\\'; result[pos++] = 't';  break;
            default:
                if (c < 0x20) {
                    /* 控制字符转义为 \u00XX */
                    pos += snprintf(result + pos, 7, "\\u%04x", c);
                } else {
                    result[pos++] = c;
                }
                break;
        }
    }
    result[pos] = '\0';
    return result;
}

/* 发送 JSON 请求 */
static int send_request(ainos_ctx* ctx, const char* json_request) {
    if (!ctx || ctx->sock == INVALID_SOCKET_VALUE) {
        return AINOS_ERR_NOT_INIT;
    }

    size_t len = strlen(json_request);
    size_t sent = 0;

    while (sent < len) {
        int n = send(ctx->sock, json_request + sent, (int)(len - sent), 0);
        if (n < 0) {
            ctx->connected = 0;
            return AINOS_ERR_CONNECT;
        }
        sent += n;
    }

    /* 发送换行符作为消息结束 */
    char newline = '\n';
    int n = send(ctx->sock, &newline, 1, 0);
    if (n < 0) {
        ctx->connected = 0;
        return AINOS_ERR_CONNECT;
    }

    return AINOS_OK;
}

/* 接收 JSON 响应 */
static char* recv_response(ainos_ctx* ctx) {
    if (!ctx || ctx->sock == INVALID_SOCKET_VALUE) {
        return NULL;
    }

    /* 设置接收超时 */
#ifdef _WIN32
    int timeout = 10000; /* 10 秒 */
    setsockopt(ctx->sock, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));
#else
    struct timeval timeout;
    timeout.tv_sec = 10;
    timeout.tv_usec = 0;
    setsockopt(ctx->sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
#endif

    /* 读取响应，直到换行符 */
    size_t capacity = 4096;
    size_t length = 0;
    char* buffer = (char*)malloc(capacity);
    if (!buffer) return NULL;

    while (1) {
        char c;
        int n = recv(ctx->sock, &c, 1, 0);
        if (n <= 0) {
            break;
        }
        if (c == '\n') {
            break;
        }

        if (length + 1 >= capacity) {
            capacity *= 2;
            char* newbuf = (char*)realloc(buffer, capacity);
            if (!newbuf) {
                free(buffer);
                return NULL;
            }
            buffer = newbuf;
        }
        buffer[length++] = c;
    }

    buffer[length] = '\0';
    return buffer;
}

/* 解析 JSON 响应 */
static ainos_resp* parse_response(const char* json) {
    ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
    if (!resp) return NULL;

    resp->output = NULL;
    resp->source = NULL;
    resp->error_message = NULL;
    resp->error_code = 0;

    if (!json || strlen(json) == 0) {
        resp->error_code = AINOS_ERR_INTERNAL;
        resp->error_message = strdup("Empty response");
        return resp;
    }

    /* 简单 JSON 解析: 查找关键字段 */
    const char* type_str = strstr(json, "\"type\"");
    if (type_str) {
        const char* val = strchr(type_str, ':');
        if (val) {
            val++;
            while (*val == ' ' || *val == '\t') val++;
            if (strstr(val, "Error")) {
                resp->error_code = AINOS_ERR_INTERNAL;
                /* 查找 error_message */
                const char* msg = strstr(json, "\"message\"");
                if (msg) {
                    const char* msg_val = strchr(msg, ':');
                    if (msg_val) {
                        msg_val++;
                        while (*msg_val == ' ' || *msg_val == '\t') msg_val++;
                        if (*msg_val == '"') {
                            msg_val++;
                            const char* end = strchr(msg_val, '"');
                            if (end) {
                                size_t len = end - msg_val;
                                resp->error_message = (char*)malloc(len + 1);
                                if (resp->error_message) {
                                    strncpy(resp->error_message, msg_val, len);
                                    resp->error_message[len] = '\0';
                                }
                            }
                        }
                    }
                }
                return resp;
            }
        }
    }

    /* 提取 output */
    const char* output = strstr(json, "\"output\"");
    if (output) {
        const char* val = strchr(output, ':');
        if (val) {
            val++;
            while (*val == ' ' || *val == '\t') val++;
            if (*val == '"') {
                val++;
                const char* end = strchr(val, '"');
                if (end) {
                    size_t len = end - val;
                    resp->output = (char*)malloc(len + 1);
                    if (resp->output) {
                        strncpy(resp->output, val, len);
                        resp->output[len] = '\0';
                    }
                }
            }
        }
    }

    /* 提取 tokens_generated */
    const char* tokens = strstr(json, "\"tokens_generated\"");
    if (tokens) {
        const char* val = strchr(tokens, ':');
        if (val) {
            resp->tokens_generated = atoi(val + 1);
        }
    }

    /* 提取 inference_ms */
    const char* ms = strstr(json, "\"inference_ms\"");
    if (ms) {
        const char* val = strchr(ms, ':');
        if (val) {
            resp->inference_ms = atoll(val + 1);
        }
    }

    /* 提取 source */
    const char* source = strstr(json, "\"source\"");
    if (source) {
        const char* val = strchr(source, ':');
        if (val) {
            val++;
            while (*val == ' ' || *val == '\t') val++;
            if (*val == '"') {
                val++;
                const char* end = strchr(val, '"');
                if (end) {
                    size_t len = end - val;
                    resp->source = (char*)malloc(len + 1);
                    if (resp->source) {
                        strncpy(resp->source, val, len);
                        resp->source[len] = '\0';
                    }
                }
            }
        }
    }

    /* 提取 error_code */
    const char* code = strstr(json, "\"code\"");
    if (code && !resp->error_code) {
        const char* val = strchr(code, ':');
        if (val) {
            resp->error_code = atoi(val + 1);
        }
    }

    return resp;
}

/* 执行推理请求 */
ainos_resp* ainos_infer(ainos_ctx* ctx, const char* model,
                        const char* prompt, ainos_infer_opts* opts) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = AINOS_ERR_NOT_INIT;
            resp->error_message = strdup("Not connected");
        }
        return resp;
    }

    /* 构建 JSON 请求 */
    char* escaped_prompt = json_escape(prompt ? prompt : "");
    char* escaped_model = json_escape(model ? model : "default");

    float temp = opts ? opts->temperature : 0.7f;
    int max_tok = opts ? opts->max_tokens : 512;

    char request[8192];
    snprintf(request, sizeof(request),
        "{\"type\":\"Inference\",\"model\":\"%s\",\"prompt\":\"%s\""
        ",\"temperature\":%.1f,\"max_tokens\":%d}",
        escaped_model, escaped_prompt, temp, max_tok);

    free(escaped_prompt);
    free(escaped_model);

    int ret = send_request(ctx, request);
    if (ret != AINOS_OK) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = ret;
            resp->error_message = strdup("Send failed");
        }
        return resp;
    }

    char* response = recv_response(ctx);
    if (!response) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = AINOS_ERR_TIMEOUT;
            resp->error_message = strdup("No response");
        }
        return resp;
    }

    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 获取系统状态 */
ainos_resp* ainos_get_info(ainos_ctx* ctx) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = AINOS_ERR_NOT_INIT;
            resp->error_message = strdup("Not connected");
        }
        return resp;
    }

    const char* request = "{\"type\":\"Status\"}";
    int ret = send_request(ctx, request);
    if (ret != AINOS_OK) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = ret;
            resp->error_message = strdup("Send failed");
        }
        return resp;
    }

    char* response = recv_response(ctx);
    if (!response) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) {
            resp->error_code = AINOS_ERR_TIMEOUT;
            resp->error_message = strdup("No response");
        }
        return resp;
    }

    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 释放响应 */
void ainos_resp_free(ainos_resp* resp) {
    if (resp) {
        free(resp->output);
        free(resp->source);
        free(resp->error_message);
        free(resp);
    }
}

/* 销毁上下文 */
void ainos_destroy(ainos_ctx* ctx) {
    if (ctx) {
        if (ctx->sock != INVALID_SOCKET_VALUE) {
            close(ctx->sock);
        }
        ctx->connected = 0;
        free(ctx);
    }

#ifdef _WIN32
    WSACleanup();
#endif
}

/* 高级 API: 获取嵌入向量 */
ainos_resp* ainos_embed(ainos_ctx* ctx, const char* text) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) { resp->error_code = AINOS_ERR_NOT_INIT; resp->error_message = strdup("Not connected"); }
        return resp;
    }
    char* escaped = json_escape(text ? text : "");
    char request[8192];
    snprintf(request, sizeof(request), "{\"type\":\"Inference\",\"model\":\"embed\",\"prompt\":\"%s\"}", escaped);
    free(escaped);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    if (!response) { ainos_resp* r = calloc(1, sizeof(ainos_resp)); if(r){r->error_code=AINOS_ERR_TIMEOUT;r->error_message=strdup("No response");} return r; }
    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 高级 API: 语义搜索 */
ainos_resp* ainos_search(ainos_ctx* ctx, const char* query, int max_results) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = (ainos_resp*)calloc(1, sizeof(ainos_resp));
        if (resp) { resp->error_code = AINOS_ERR_NOT_INIT; resp->error_message = strdup("Not connected"); }
        return resp;
    }
    char* escaped = json_escape(query ? query : "");
    char request[8192];
    snprintf(request, sizeof(request), "{\"type\":\"Inference\",\"model\":\"search\",\"prompt\":\"%s\",\"max_tokens\":%d}", escaped, max_results);
    free(escaped);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    if (!response) { ainos_resp* r = calloc(1, sizeof(ainos_resp)); if(r){r->error_code=AINOS_ERR_TIMEOUT;r->error_message=strdup("No response");} return r; }
    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 高级 API: 上下文存储 */
ainos_resp* ainos_ctx_store(ainos_ctx* ctx, const char* key, const char* value) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = calloc(1, sizeof(ainos_resp));
        if (resp) { resp->error_code = AINOS_ERR_NOT_INIT; resp->error_message = strdup("Not connected"); }
        return resp;
    }
    char* escaped_key = json_escape(key ? key : "");
    char* escaped_val = json_escape(value ? value : "");
    char request[16384];
    snprintf(request, sizeof(request), "{\"type\":\"ContextStore\",\"key\":\"%s\",\"value\":\"%s\"}", escaped_key, escaped_val);
    free(escaped_key);
    free(escaped_val);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    if (!response) { ainos_resp* r = calloc(1, sizeof(ainos_resp)); if(r){r->error_code=AINOS_ERR_TIMEOUT;r->error_message=strdup("No response");} return r; }
    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 高级 API: 上下文检索 */
ainos_resp* ainos_ctx_get(ainos_ctx* ctx, const char* key) {
    if (!ctx || !ctx->connected) {
        ainos_resp* resp = calloc(1, sizeof(ainos_resp));
        if (resp) { resp->error_code = AINOS_ERR_NOT_INIT; resp->error_message = strdup("Not connected"); }
        return resp;
    }
    char* escaped_key = json_escape(key ? key : "");
    char request[8192];
    snprintf(request, sizeof(request), "{\"type\":\"ContextRetrieve\",\"key\":\"%s\"}", escaped_key);
    free(escaped_key);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    if (!response) { ainos_resp* r = calloc(1, sizeof(ainos_resp)); if(r){r->error_code=AINOS_ERR_TIMEOUT;r->error_message=strdup("No response");} return r; }
    ainos_resp* resp = parse_response(response);
    free(response);
    return resp;
}

/* 高级 API: 模型加载 */
int ainos_model_load(ainos_ctx* ctx, const char* path) {
    if (!ctx || !ctx->connected) return AINOS_ERR_NOT_INIT;
    char* escaped = json_escape(path ? path : "");
    char request[8192];
    snprintf(request, sizeof(request), "{\"type\":\"ModelLoad\",\"path\":\"%s\"}", escaped);
    free(escaped);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    free(response);
    return AINOS_OK;
}

/* 高级 API: 模型卸载 */
int ainos_model_unload(ainos_ctx* ctx, const char* model_id) {
    if (!ctx || !ctx->connected) return AINOS_ERR_NOT_INIT;
    char* escaped = json_escape(model_id ? model_id : "");
    char request[8192];
    snprintf(request, sizeof(request), "{\"type\":\"ModelUnload\",\"model_id\":\"%s\"}", escaped);
    free(escaped);
    send_request(ctx, request);
    char* response = recv_response(ctx);
    free(response);
    return AINOS_OK;
}

#ifdef __cplusplus
}
#endif