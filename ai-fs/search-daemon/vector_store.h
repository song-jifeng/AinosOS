#ifndef AINOS_AI_FS_VECTOR_STORE_H
#define AINOS_AI_FS_VECTOR_STORE_H

#include <vector>
#include <string>
#include <memory>
#include <mutex>
#include <unordered_map>

namespace ainos {
namespace ai_fs {

// 向量存储项
struct VectorItem {
    std::string id;
    std::vector<float> vector;
    std::string metadata; // JSON 格式的元数据
};

// 搜索结果
struct VectorSearchResult {
    std::string id;
    float distance;
    std::string metadata;
};

// HNSW 参数
struct HNSWParams {
    size_t M = 16;              // 每层的最大连接数
    size_t ef_construction = 200; // 构建时的搜索宽度
    size_t ef_search = 50;       // 搜索时的宽度
    size_t max_elements = 1000000;
};

// 向量存储接口
class VectorStore {
public:
    virtual ~VectorStore() = default;
    
    // 初始化
    virtual bool initialize(size_t dimension, const HNSWParams& params) = 0;
    
    // 添加向量
    virtual bool add(const VectorItem& item) = 0;
    virtual bool add_batch(const std::vector<VectorItem>& items) = 0;
    
    // 删除向量
    virtual bool remove(const std::string& id) = 0;
    
    // 搜索
    virtual std::vector<VectorSearchResult> search(
        const std::vector<float>& query, 
        size_t k) = 0;
    
    // 持久化
    virtual bool save(const std::string& path) = 0;
    virtual bool load(const std::string& path) = 0;
    
    // 统计信息
    virtual size_t size() const = 0;
    virtual size_t dimension() const = 0;
};

// HNSW 向量存储实现
class HNSWVectorStore : public VectorStore {
public:
    HNSWVectorStore();
    ~HNSWVectorStore() override;
    
    bool initialize(size_t dimension, const HNSWParams& params) override;
    
    bool add(const VectorItem& item) override;
    bool add_batch(const std::vector<VectorItem>& items) override;
    
    bool remove(const std::string& id) override;
    
    std::vector<VectorSearchResult> search(
        const std::vector<float>& query, 
        size_t k) override;
    
    bool save(const std::string& path) override;
    bool load(const std::string& path) override;
    
    size_t size() const override;
    size_t dimension() const override;
    
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
    
    mutable std::mutex mutex_;
    std::unordered_map<std::string, size_t> id_to_label_;
    std::unordered_map<size_t, std::string> label_to_id_;
    std::unordered_map<std::string, std::string> metadata_store_;
    size_t next_label_ = 0;
};

// 创建向量存储
std::unique_ptr<VectorStore> create_vector_store();

} // namespace ai_fs
} // namespace ainos

#endif // AINOS_AI_FS_VECTOR_STORE_H