#ifndef AINOS_AI_FS_H
#define AINOS_AI_FS_H

#include <string>
#include <vector>
#include <cstdint>
#include <memory>

namespace ainos {
namespace ai_fs {

// 版本信息
constexpr const char* VERSION = "1.0.0";

// 文件元数据
struct FileMetadata {
    std::string path;
    std::string mime_type;
    uint64_t size;
    uint64_t mtime;
    std::string content_hash;
};

// 搜索结果
struct SearchResult {
    std::string path;
    float similarity_score;
    std::string snippet;
    FileMetadata metadata;
};

// 索引状态
enum class IndexStatus {
    IDLE,
    INDEXING,
    PAUSED,
    ERROR
};

struct IndexStats {
    IndexStatus status;
    uint64_t total_files;
    uint64_t indexed_files;
    uint64_t pending_files;
    uint64_t failed_files;
};

// 搜索选项
struct SearchOptions {
    uint32_t max_results = 10;
    float min_similarity = 0.5f;
    bool include_content = false;
    std::vector<std::string> file_types;
};

// 公共 API
class AIFileSystem {
public:
    virtual ~AIFileSystem() = default;
    
    // 初始化文件系统
    virtual bool initialize(const std::string& root_path, const std::string& index_path) = 0;
    
    // 语义搜索
    virtual std::vector<SearchResult> search(const std::string& query, const SearchOptions& options) = 0;
    
    // 索引控制
    virtual bool start_indexing() = 0;
    virtual bool pause_indexing() = 0;
    virtual bool resume_indexing() = 0;
    virtual IndexStats get_index_stats() const = 0;
    
    // 手动添加/删除文件
    virtual bool index_file(const std::string& path) = 0;
    virtual bool remove_file(const std::string& path) = 0;
    
    // 关闭
    virtual void shutdown() = 0;
};

// 创建文件系统实例
std::unique_ptr<AIFileSystem> create_ai_filesystem();

} // namespace ai_fs
} // namespace ainos

#endif // AINOS_AI_FS_H