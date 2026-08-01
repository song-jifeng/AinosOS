// daemon/policy_daemon.c
// Ainos OS 策略守护进程 - 管理 AI 数据访问权限
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <signal.h>
#include "ainos/ai_policy.h"
#include "policy-engine/policy_engine.h"
#include "enforcer/enforcer.h"

static volatile int running = 1;

void signal_handler(int sig) {
    if (sig == SIGINT || sig == SIGTERM) {
        running = 0;
    }
}

static void print_usage(const char* prog) {
    printf("Ainos Policy Daemon v0.1.0\n");
    printf("Usage: %s [options]\n", prog);
    printf("Options:\n");
    printf("  -c, --config PATH  策略配置文件路径\n");
    printf("  -p, --policy  PATH 策略文件目录\n");
    printf("  -s, --socket  PATH IPC socket路径\n");
    printf("  -d, --daemon       后台运行\n");
    printf("  -v, --verbose      详细输出\n");
}

int main(int argc, char** argv) {
    const char* config_path = "/etc/ainos/ai-daemon.conf";
    const char* policy_dir = "/etc/ainos/policy/";
    const char* socket_path = "/var/run/ainos/ai-policyd.sock";
    int daemon_mode = 0;
    int verbose = 0;

    // 解析参数
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-c") == 0 && i + 1 < argc) {
            config_path = argv[++i];
        } else if (strcmp(argv[i], "-p") == 0 && i + 1 < argc) {
            policy_dir = argv[++i];
        } else if (strcmp(argv[i], "-s") == 0 && i + 1 < argc) {
            socket_path = argv[++i];
        } else if (strcmp(argv[i], "-d") == 0) {
            daemon_mode = 1;
        } else if (strcmp(argv[i], "-v") == 0) {
            verbose = 1;
        } else {
            print_usage(argv[0]);
            return 1;
        }
    }

    if (verbose) {
        printf("[ai-policyd] Starting...\n");
        printf("  Config: %s\n", config_path);
        printf("  Policy: %s\n", policy_dir);
        printf("  Socket: %s\n", socket_path);
    }

    // 注册信号处理
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    // 初始化策略引擎
    ai_policy_engine_t* engine = ai_policy_engine_create();
    if (!engine) {
        fprintf(stderr, "[ai-policyd] Failed to create policy engine\n");
        return 1;
    }

    // 加载策略
    if (ai_policy_engine_load_dir(engine, policy_dir) != 0) {
        fprintf(stderr, "[ai-policyd] Failed to load policies from %s\n", policy_dir);
    } else if (verbose) {
        printf("[ai-policyd] Policies loaded from %s\n", policy_dir);
    }

    // 初始化执行器
    ai_policy_enforcer_t* enforcer = ai_policy_enforcer_create(engine);
    if (!enforcer) {
        fprintf(stderr, "[ai-policyd] Failed to create enforcer\n");
        ai_policy_engine_destroy(engine);
        return 1;
    }

    // 创建 IPC Socket
    struct sockaddr_un addr;
    int server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("[ai-policyd] socket");
        return 1;
    }

    unlink(socket_path);
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("[ai-policyd] bind");
        close(server_fd);
        return 1;
    }

    listen(server_fd, 5);
    printf("[ai-policyd] Running (socket: %s)\n", socket_path);

    // 主循环
    while (running) {
        struct sockaddr_un client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);

        if (client_fd < 0) {
            if (running) perror("[ai-policyd] accept");
            continue;
        }

        // 处理权限检查请求
        char buffer[4096];
        ssize_t n = read(client_fd, buffer, sizeof(buffer) - 1);
        if (n > 0) {
            buffer[n] = '\0';

            // 解析请求并检查权限
            // TODO: 实现完整的请求解析
            ai_policy_decision_t decision = ai_policy_enforcer_check(
                enforcer, "ai-app", AI_ACTION_READ, "file", buffer);

            // 发送响应
            const char* response = (decision == AI_POLICY_ALLOW) ? "allow" : "deny";
            write(client_fd, response, strlen(response));
        }

        close(client_fd);
    }

    // 清理
    printf("[ai-policyd] Shutting down...\n");
    ai_policy_enforcer_destroy(enforcer);
    ai_policy_engine_destroy(engine);
    close(server_fd);
    unlink(socket_path);
    printf("[ai-policyd] Stopped\n");

    return 0;
}