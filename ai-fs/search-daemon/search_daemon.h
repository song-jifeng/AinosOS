// search-daemon/search_daemon.h
// Ainos OS AI-FS 搜索守护进程头文件
#ifndef AINOS_FS_SEARCH_DAEMON_H
#define AINOS_FS_SEARCH_DAEMON_H

#include <string>
#include <vector>
#include <functional>
#include "ainos/ai_fs.h"
#include "indexer.h"
#include "vector_store.h"

namespace ainos {
namespace fs {

/// 搜索守护进程配置
struct SearchDaemonConfig {
    std::string mount_point = "/mnt/ai-fs";
    std::string index_path = "/var/lib/ainos/ai-fs/index";
    std::string socket_path = "/var/run/ainos/ai-fsd.sock";
    int num_index_threads = 2;
    size_t cache_size_mb = 512;
    bool auto_index = true;
    bool enable_watch = true;
};

/// 搜索请求
struct SearchRequest {
    std::string query;
    std::string directory;
    int max_results = 20;
    float min_score = 0.3f;
    uint32_t flags = 0;
};

/// 搜索守护进程
class SearchDaemon {
public:
    SearchDaemon();
    ~SearchDaemon();

    // 初始化
    bool Initialize(const SearchDaemonConfig& config);

    // 启动 (FUSE挂载 + IPC监听)
    bool Start();

    // 停止
    void Stop();

    // 语义搜索
    std::vector<ai_fs_search_result_t> Search(const SearchRequest& req);

    // 索引文件/目录
    bool IndexPath(const std::string& path);
    bool RemoveIndex(const std::string& path);

    // 获取状态
    SearchDaemonConfig GetConfig() const { return config_; }
    IndexerStats GetIndexStats() const;

    // 回调
    using SearchCallback = std::function<void(const ai_fs_search_result_t&)>;

private:
    SearchDaemonConfig config_;
    Indexer* indexer_ = nullptr;
    VectorStore* vector_store_ = nullptr;
    bool running_ = false;

    // FUSE 处理
    void HandleFuseLookup(const std::string& path);
    void HandleFuseReaddir(const std::string& path,
                          std::vector<std::string>& entries);

    // IPC 处理
    void HandleIpcRequest(const std::string& request, std::string& response);
    void IpcListenerThread();

    // 索引线程
    void IndexWorkerThread();
};

} // namespace fs
} // namespace ainos

#endif // AINOS_FS_SEARCH_DAEMON_H