#include "indexer.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <algorithm>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>
#include <openssl/md5.h>

namespace fs = std::filesystem;

namespace ainos {
namespace ai_fs {

// TextExtractor 实现
bool TextExtractor::can_extract(const std::string& mime_type) const {
    return mime_type.find("text/") == 0 || 
           mime_type == "application/json" ||
           mime_type == "application/xml";
}

std::string TextExtractor::extract(const std::string& file_path) {
    std::ifstream file(file_path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Failed to open file: " + file_path);
    }
    
    std::stringstream buffer;
    buffer << file.rdbuf();
    return buffer.str();
}

// PDFExtractor 实现
bool PDFExtractor::can_extract(const std::string& mime_type) const {
    return mime_type == "application/pdf";
}

std::string PDFExtractor::extract(const std::string& file_path) {
    // 简化实现：实际应使用 poppler 或其他 PDF 库
    // 这里仅作示例
    std::string content = "[PDF content extraction not implemented]\n";
    content += "File: " + file_path;
    return content;
}

// CodeExtractor 实现
bool CodeExtractor::can_extract(const std::string& mime_type) const {
    static const std::vector<std::string> code_types = {
        "text/x-c", "text/x-c++", "text/x-python", "text/x-java",
        "text/x-javascript", "text/x-rust", "text/x-go"
    };
    
    return std::find(code_types.begin(), code_types.end(), mime_type) != code_types.end();
}

std::string CodeExtractor::extract(const std::string& file_path) {
    std::ifstream file(file_path);
    if (!file) {
        throw std::runtime_error("Failed to open file: " + file_path);
    }
    
    std::stringstream buffer;
    std::string line;
    int line_num = 1;
    
    // 添加行号以保持代码结构信息
    while (std::getline(file, line)) {
        buffer << line_num++ << ": " << line << "\n";
    }
    
    return buffer.str();
}

// IPCEmbeddingGenerator 实现
class IPCEmbeddingGenerator::Impl {
public:
    explicit Impl(const std::string& socket_path) 
        : socket_path_(socket_path), sockfd_(-1), embedding_dim_(768) {
        connect();
    }
    
    ~Impl() {
        if (sockfd_ >= 0) {
            close(sockfd_);
        }
    }
    
    std::vector<float> generate(const std::string& text) {
        std::lock_guard<std::mutex> lock(socket_mutex_);
        
        if (sockfd_ < 0 && !connect()) {
            throw std::runtime_error("Not connected to AI Runtime");
        }
        
        // 构造请求: [size:4][text:size]
        uint32_t text_size = static_cast<uint32_t>(text.size());
        
        if (send(sockfd_, &text_size, sizeof(text_size), 0) != sizeof(text_size)) {
            reconnect();
            throw std::runtime_error("Failed to send text size");
        }
        
        if (send(sockfd_, text.data(), text_size, 0) != static_cast<ssize_t>(text_size)) {
            reconnect();
            throw std::runtime_error("Failed to send text");
        }
        
        // 接收响应: [dim:4][embedding:dim*4]
        uint32_t dim;
        if (recv(sockfd_, &dim, sizeof(dim), MSG_WAITALL) != sizeof(dim)) {
            reconnect();
            throw std::runtime_error("Failed to receive embedding dimension");
        }
        
        std::vector<float> embedding(dim);
        size_t bytes_to_recv = dim * sizeof(float);
        
        if (recv(sockfd_, embedding.data(), bytes_to_recv, MSG_WAITALL) != 
            static_cast<ssize_t>(bytes_to_recv)) {
            reconnect();
            throw std::runtime_error("Failed to receive embedding");
        }
        
        return embedding;
    }
    
    size_t embedding_dim() const { return embedding_dim_; }
    
private:
    bool connect() {
        sockfd_ = socket(AF_UNIX, SOCK_STREAM, 0);
        if (sockfd_ < 0) {
            return false;
        }
        
        struct sockaddr_un addr;
        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);
        
        if (::connect(sockfd_, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
            close(sockfd_);
            sockfd_ = -1;
            return false;
        }
        
        return true;
    }
    
    void reconnect() {
        if (sockfd_ >= 0) {
            close(sockfd_);
            sockfd_ = -1;
        }
        connect();
    }
    
    std::string socket_path_;
    int sockfd_;
    size_t embedding_dim_;
    std::mutex socket_mutex_;
};

IPCEmbeddingGenerator::IPCEmbeddingGenerator(const std::string& socket_path)
    : impl_(std::make_unique<Impl>(socket_path)) {}

IPCEmbeddingGenerator::~IPCEmbeddingGenerator() = default;

std::vector<float> IPCEmbeddingGenerator::generate(const std::string& text) {
    return impl_->generate(text);
}

size_t IPCEmbeddingGenerator::embedding_dim() const {
    return impl_->embedding_dim();
}

// Indexer 实现
Indexer::Indexer(const std::string& root_path,
                 std::shared_ptr<EmbeddingGenerator> embedding_gen)
    : root_path_(root_path), embedding_gen_(std::move(embedding_gen)) {
    
    // 注册默认提取器
    register_extractor(std::make_unique<TextExtractor>());
    register_extractor(std::make_unique<PDFExtractor>());
    register_extractor(std::make_unique<CodeExtractor>());
}

Indexer::~Indexer() {
    stop();
}

bool Indexer::start() {
    if (running_) {
        return false;
    }
    
    running_ = true;
    paused_ = false;
    
    // 启动工作线程
    size_t num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4;
    
    for (size_t i = 0; i < num_threads; ++i) {
        worker_threads_.emplace_back(&Indexer::worker_thread, this);
    }
    
    return true;
}

void Indexer::stop() {
    if (!running_) {
        return;
    }
    
    running_ = false;
    queue_cv_.notify_all();
    
    for (auto& thread : worker_threads_) {
        if (thread.joinable()) {
            thread.join();
        }
    }
    
    worker_threads_.clear();
}

void Indexer::pause() {
    paused_ = true;
}

void Indexer::resume() {
    paused_ = false;
    queue_cv_.notify_all();
}

void Indexer::enqueue_task(const IndexTask& task) {
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        task_queue_.push(task);
    }
    queue_cv_.notify_one();
}

void Indexer::set_index_callback(IndexCallback callback) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    index_callback_ = std::move(callback);
}

void Indexer::set_error_callback(ErrorCallback callback) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    error_callback_ = std::move(callback);
}

size_t Indexer::pending_tasks() const {
    std::lock_guard<std::mutex> lock(queue_mutex_);
    return task_queue_.size();
}

void Indexer::register_extractor(std::unique_ptr<ContentExtractor> extractor) {
    extractors_.push_back(std::move(extractor));
}

void Indexer::worker_thread() {
    while (running_) {
        IndexTask task;
        
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            queue_cv_.wait(lock, [this] { 
                return !running_ || (!task_queue_.empty() && !paused_); 
            });
            
            if (!running_) {
                break;
            }
            
            if (task_queue_.empty()) {
                continue;
            }
            
            task = task_queue_.front();
            task_queue_.pop();
        }
        
        process_task(task);
    }
}

void Indexer::process_task(const IndexTask& task) {
    try {
        if (task.type == IndexTask::Type::REMOVE) {
            // 移除文件的处理逻辑
            std::lock_guard<std::mutex> lock(hash_mutex_);
            file_hashes_.erase(task.path);
            return;
        }
        
        // 检查文件是否存在
        if (!fs::exists(task.path)) {
            return;
        }
        
        // 计算文件哈希
        std::ifstream file(task.path, std::ios::binary);
        if (!file) {
            throw std::runtime_error("Cannot open file");
        }
        
        MD5_CTX md5_ctx;
        MD5_Init(&md5_ctx);
        
        char buffer[8192];
        while (file.read(buffer, sizeof(buffer)) || file.gcount() > 0) {
            MD5_Update(&md5_ctx, buffer, file.gcount());
        }
        
        unsigned char hash[MD5_DIGEST_LENGTH];
        MD5_Final(hash, &md5_ctx);
        
        std::string hash_str;
        for (int i = 0; i < MD5_DIGEST_LENGTH; ++i) {
            char hex[3];
            snprintf(hex, sizeof(hex), "%02x", hash[i]);
            hash_str += hex;
        }
        
        // 检查是否需要重新索引
        {
            std::lock_guard<std::mutex> lock(hash_mutex_);
            auto it = file_hashes_.find(task.path);
            if (it != file_hashes_.end() && it->second == hash_str) {
                return; // 文件未变化
            }
            file_hashes_[task.path] = hash_str;
        }
        
        // 提取内容
        std::string mime_type = detect_mime_type(task.path);
        std::string content = extract_content(task.path, mime_type);
        
        if (content.empty()) {
            return;
        }
        
        // 生成嵌入向量
        std::vector<float> embedding = embedding_gen_->generate(content);
        
        // 创建文档
        Document doc;
        doc.path = task.path;
        doc.content = content;
        doc.mime_type = mime_type;
        doc.mtime = task.mtime;
        doc.embedding = std::move(embedding);
        
        // 回调
        std::lock_guard<std::mutex> lock(callback_mutex_);
        if (index_callback_) {
            index_callback_(doc);
        }
        
    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(callback_mutex_);
        if (error_callback_) {
            error_callback_(task.path, e.what());
        }
    }
}

std::string Indexer::extract_content(const std::string& path, const std::string& mime_type) {
    for (auto& extractor : extractors_) {
        if (extractor->can_extract(mime_type)) {
            return extractor->extract(path);
        }
    }
    return "";
}

std::string Indexer::detect_mime_type(const std::string& path) {
    // 简化的 MIME 类型检测
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    static const std::unordered_map<std::string, std::string> mime_map = {
        {".txt", "text/plain"},
        {".md", "text/markdown"},
        {".cpp", "text/x-c++"},
        {".h", "text/x-c++"},
        {".c", "text/x-c"},
        {".py", "text/x-python"},
        {".java", "text/x-java"},
        {".js", "text/x-javascript"},
        {".rs", "text/x-rust"},
        {".go", "text/x-go"},
        {".json", "application/json"},
        {".xml", "application/xml"},
        {".pdf", "application/pdf"}
    };
    
    auto it = mime_map.find(ext);
    return it != mime_map.end() ? it->second : "application/octet-stream";
}

} // namespace ai_fs
} // namespace ainos