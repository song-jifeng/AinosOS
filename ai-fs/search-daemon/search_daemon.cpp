// search-daemon/search_daemon.cpp
// Ainos OS AI-FS 搜索守护进程实现
#include "search_daemon.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace ainos {
namespace fs {

SearchDaemon::SearchDaemon() {
    indexer_ = new Indexer();
    vector_store_ = new VectorStore();
}

SearchDaemon::~SearchDaemon() {
    Stop();
    delete indexer_;
    delete vector_store_;
}

bool SearchDaemon::Initialize(const SearchDaemonConfig& config) {
    config_ = config;

    // 初始化索引器
    IndexerConfig idx_config;
    idx_config.num_threads = config_.num_index_threads;
    idx_config.cache_size_mb = config_.cache_size_mb;
    idx_config.watch_enabled = config_.enable_watch;
    if (!indexer_->Initialize(idx_config)) {
        std::cerr << "[ai-fsd] Failed to initialize indexer" << std::endl;
        return false;
    }

    // 初始化向量存储
    if (!vector_store_->Initialize(config_.index_path, 768)) {
        std::cerr << "[ai-fsd] Failed to initialize vector store" << std::endl;
        return false;
    }

    std::cout << "[ai-fsd] Initialized (index=" << config_.index_path
              << ", mount=" << config_.mount_point << ")" << std::endl;
    return true;
}

bool SearchDaemon::Start() {
    running_ = true;

    // 启动索引工作线程
    std::thread index_thread(&SearchDaemon::IndexWorkerThread, this);
    index_thread.detach();

    // 启动 IPC 监听线程
    std::thread ipc_thread(&SearchDaemon::IpcListenerThread, this);
    ipc_thread.detach();

    std::cout << "[ai-fsd] Started (FUSE mount at " << config_.mount_point << ")" << std::endl;
    return true;
}

void SearchDaemon::Stop() {
    running_ = false;
    indexer_->Stop();
}

std::vector<ai_fs_search_result_t> SearchDaemon::Search(const SearchRequest& req) {
    std::vector<ai_fs_search_result_t> results;

    // 1. 生成查询嵌入向量
    // TODO: 调用 ai-daemon 获取嵌入向量
    std::vector<float> query_embedding(768, 0.0f);

    // 2. 在向量存储中搜索相似文件
    auto vector_results = vector_store_->Search(query_embedding, req.max_results);

    // 3. 转换为搜索结果
    for (const auto& vr : vector_results) {
        ai_fs_search_result_t result;
        std::strncpy(result.path, vr.path.c_str(), sizeof(result.path) - 1);
        result.score = vr.score;
        result.file_size = vr.file_size;
        result.modified_at = vr.modified_at;
        results.push_back(result);
    }

    return results;
}

bool SearchDaemon::IndexPath(const std::string& path) {
    return indexer_->IndexPath(path);
}

IndexerStats SearchDaemon::GetIndexStats() const {
    return indexer_->GetStats();
}

void SearchDaemon::IndexWorkerThread() {
    while (running_) {
        indexer_->ProcessQueue();
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}

void SearchDaemon::IpcListenerThread() {
    struct sockaddr_un addr;
    int server_fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd < 0) return;

    unlink(config_.socket_path.c_str());

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, config_.socket_path.c_str(), sizeof(addr.sun_path) - 1);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(server_fd);
        return;
    }

    listen(server_fd, 5);

    while (running_) {
        struct sockaddr_un client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);
        if (client_fd < 0) continue;

        char buffer[4096];
        ssize_t n = read(client_fd, buffer, sizeof(buffer) - 1);
        if (n > 0) {
            buffer[n] = '\0';
            std::string response;
            HandleIpcRequest(buffer, response);
            write(client_fd, response.c_str(), response.length());
        }
        close(client_fd);
    }

    close(server_fd);
    unlink(config_.socket_path.c_str());
}

void SearchDaemon::HandleIpcRequest(const std::string& request, std::string& response) {
    // TODO: 实现IPC请求处理
    response = "{\"status\":\"ok\"}";
}

} // namespace fs
} // namespace ainos