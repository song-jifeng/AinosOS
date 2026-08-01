#ifndef AINOS_AI_FS_INDEXER_H
#define AINOS_AI_FS_INDEXER_H

#include <string>
#include <vector>
#include <memory>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <thread>
#include <unordered_map>
#include <functional>

namespace ainos {
namespace ai_fs {

// 文档内容
struct Document {
    std::string path;
    std::string content;
    std::string mime_type;
    uint64_t mtime;
    std::vector<float> embedding;
};

// 文件内容提取器基类
class ContentExtractor {
public:
    virtual ~ContentExtractor() = default;
    virtual bool can_extract(const std::string& mime_type) const = 0;
    virtual std::string extract(const std::string& file_path) = 0;
};

// 文本文件提取器
class TextExtractor : public ContentExtractor {
public:
    bool can_extract(const std::string& mime_type) const override;
    std::string extract(const std::string& file_path) override;
};

// PDF 提取器
class PDFExtractor : public ContentExtractor {
public:
    bool can_extract(const std::string& mime_type) const override;
    std::string extract(const std::string& file_path) override;
};

// 代码文件提取器
class CodeExtractor : public ContentExtractor {
public:
    bool can_extract(const std::string& mime_type) const override;
    std::string extract(const std::string& file_path) override;
};

// 索引任务
struct IndexTask {
    enum class Type {
        ADD,
        UPDATE,
        REMOVE
    };
    
    Type type;
    std::string path;
    uint64_t mtime;
};

// 嵌入生成器接口 (与 AI Runtime 通信)
class EmbeddingGenerator {
public:
    virtual ~EmbeddingGenerator() = default;
    virtual std::vector<float> generate(const std::string& text) = 0;
    virtual size_t embedding_dim() const = 0;
};

// IPC 嵌入生成器
class IPCEmbeddingGenerator : public EmbeddingGenerator {
public:
    explicit IPCEmbeddingGenerator(const std::string& socket_path);
    ~IPCEmbeddingGenerator() override;
    
    std::vector<float> generate(const std::string& text) override;
    size_t embedding_dim() const override;
    
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

// 索引回调
using IndexCallback = std::function<void(const Document&)>;
using ErrorCallback = std::function<void(const std::string&, const std::string&)>;

// 文件索引引擎
class Indexer {
public:
    Indexer(const std::string& root_path, 
            std::shared_ptr<EmbeddingGenerator> embedding_gen);
    ~Indexer();
    
    // 启动/停止
    bool start();
    void stop();
    void pause();
    void resume();
    
    // 添加索引任务
    void enqueue_task(const IndexTask& task);
    
    // 回调设置
    void set_index_callback(IndexCallback callback);
    void set_error_callback(ErrorCallback callback);
    
    // 状态查询
    bool is_running() const { return running_; }
    bool is_paused() const { return paused_; }
    size_t pending_tasks() const;
    
    // 注册内容提取器
    void register_extractor(std::unique_ptr<ContentExtractor> extractor);
    
private:
    void worker_thread();
    void process_task(const IndexTask& task);
    std::string extract_content(const std::string& path, const std::string& mime_type);
    std::string detect_mime_type(const std::string& path);
    
    std::string root_path_;
    std::shared_ptr<EmbeddingGenerator> embedding_gen_;
    
    std::vector<std::unique_ptr<ContentExtractor>> extractors_;
    
    std::queue<IndexTask> task_queue_;
    mutable std::mutex queue_mutex_;
    std::condition_variable queue_cv_;
    
    std::atomic<bool> running_{false};
    std::atomic<bool> paused_{false};
    std::vector<std::thread> worker_threads_;
    
    IndexCallback index_callback_;
    ErrorCallback error_callback_;
    std::mutex callback_mutex_;
    
    // 文件哈希缓存 (避免重复索引)
    std::unordered_map<std::string, std::string> file_hashes_;
    std::mutex hash_mutex_;
};

} // namespace ai_fs
} // namespace ainos

#endif // AINOS_AI_FS_INDEXER_H