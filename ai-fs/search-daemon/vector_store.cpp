// search-daemon/vector_store.cpp
// Ainos OS AI-FS 向量存储实现
#include "vector_store.h"
#include <fstream>
#include <iostream>
#include <algorithm>
#include <cmath>
#include <cstring>

namespace ainos {
namespace fs {

VectorStore::VectorStore() {}
VectorStore::~VectorStore() { Close(); }

bool VectorStore::Initialize(const std::string& path, size_t dimension) {
    index_path_ = path;
    dimension_ = dimension;

    // 创建目录
    std::string cmd = "mkdir -p " + path;
    system(cmd.c_str());

    // 尝试加载已有索引
    LoadIndex();

    initialized_ = true;
    return true;
}

void VectorStore::Close() {
    if (initialized_) {
        SaveIndex();
    }
    initialized_ = false;
}

bool VectorStore::AddVector(const std::string& file_path,
                             const std::vector<float>& embedding,
                             uint64_t file_size,
                             uint64_t modified_at) {
    if (!initialized_ || embedding.size() != dimension_) return false;

    std::lock_guard<std::mutex> lock(mutex_);

    // 检查是否已存在
    auto it = std::find_if(entries_.begin(), entries_.end(),
        [&](const IndexEntry& e) { return e.path == file_path; });

    if (it != entries_.end()) {
        // 更新
        it->embedding = embedding;
        it->file_size = file_size;
        it->modified_at = modified_at;
        it->indexed_at = std::time(nullptr);
    } else {
        // 新增
        IndexEntry entry;
        entry.path = file_path;
        entry.embedding = embedding;
        entry.file_size = file_size;
        entry.modified_at = modified_at;
        entry.indexed_at = std::time(nullptr);
        entries_.push_back(entry);
    }

    dirty_ = true;
    return true;
}

bool VectorStore::RemoveVector(const std::string& file_path) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = std::remove_if(entries_.begin(), entries_.end(),
        [&](const IndexEntry& e) { return e.path == file_path; });

    if (it != entries_.end()) {
        entries_.erase(it, entries_.end());
        dirty_ = true;
        return true;
    }
    return false;
}

std::vector<VectorStore::SearchResult> VectorStore::Search(
    const std::vector<float>& query_embedding,
    int top_k) {

    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<SearchResult> results;

    if (entries_.empty() || query_embedding.size() != dimension_) {
        return results;
    }

    // 计算余弦相似度
    for (const auto& entry : entries_) {
        float similarity = CosineSimilarity(query_embedding, entry.embedding);

        SearchResult result;
        result.path = entry.path;
        result.score = similarity;
        result.file_size = entry.file_size;
        result.modified_at = entry.modified_at;
        results.push_back(result);
    }

    // 按相似度排序
    std::sort(results.begin(), results.end(),
        [](const SearchResult& a, const SearchResult& b) {
            return a.score > b.score;
        });

    // 截取 top-k
    if (results.size() > (size_t)top_k) {
        results.resize(top_k);
    }

    return results;
}

float VectorStore::CosineSimilarity(const std::vector<float>& a,
                                     const std::vector<float>& b) {
    float dot = 0.0f, norm_a = 0.0f, norm_b = 0.0f;
    for (size_t i = 0; i < a.size(); i++) {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }
    if (norm_a == 0.0f || norm_b == 0.0f) return 0.0f;
    return dot / (std::sqrt(norm_a) * std::sqrt(norm_b));
}

bool VectorStore::SaveIndex() {
    if (!dirty_) return true;

    std::string indexPath = index_path_ + "/vectors.idx";
    std::string metaPath = index_path_ + "/vectors.meta";

    std::lock_guard<std::mutex> lock(mutex_);

    // 保存向量数据 (二进制)
    std::ofstream vfile(indexPath, std::ios::binary);
    if (!vfile) return false;

    uint32_t count = entries_.size();
    uint32_t dim = dimension_;
    vfile.write((char*)&count, sizeof(count));
    vfile.write((char*)&dim, sizeof(dim));

    for (const auto& entry : entries_) {
        vfile.write((char*)entry.embedding.data(), dim * sizeof(float));
    }
    vfile.close();

    // 保存元数据 (JSON)
    std::ofstream mfile(metaPath);
    if (!mfile) return false;

    mfile << "{\"entries\":[";
    for (size_t i = 0; i < entries_.size(); i++) {
        if (i > 0) mfile << ",";
        mfile << "{\"path\":\"" << entries_[i].path
              << "\",\"size\":" << entries_[i].file_size
              << ",\"modified\":" << entries_[i].modified_at
              << ",\"indexed\":" << entries_[i].indexed_at
              << "}";
    }
    mfile << "]}";
    mfile.close();

    dirty_ = false;
    return true;
}

bool VectorStore::LoadIndex() {
    std::string indexPath = index_path_ + "/vectors.idx";
    std::ifstream vfile(indexPath, std::ios::binary);
    if (!vfile) return false;

    uint32_t count, dim;
    vfile.read((char*)&count, sizeof(count));
    vfile.read((char*)&dim, sizeof(dim));

    if (dim != dimension_) return false;

    // 读取元数据
    std::vector<std::string> paths;
    std::vector<uint64_t> sizes;
    std::vector<uint64_t> times;

    std::string metaPath = index_path_ + "/vectors.meta";
    std::ifstream mfile(metaPath);
    if (mfile) {
        std::string line;
        while (std::getline(mfile, line)) {
            // Simple JSON parsing for paths
            auto pos = line.find("\"path\":\"");
            if (pos != std::string::npos) {
                pos += 8;
                auto end = line.find("\"", pos);
                if (end != std::string::npos) {
                    paths.push_back(line.substr(pos, end - pos));
                }
            }
        }
    }

    // 读取向量
    for (uint32_t i = 0; i < count; i++) {
        std::vector<float> embedding(dim);
        vfile.read((char*)embedding.data(), dim * sizeof(float));

        IndexEntry entry;
        entry.path = (i < paths.size()) ? paths[i] : ("file_" + std::to_string(i));
        entry.embedding = embedding;
        entry.file_size = (i < sizes.size()) ? sizes[i] : 0;
        entry.modified_at = (i < times.size()) ? times[i] : 0;
        entry.indexed_at = std::time(nullptr);
        entries_.push_back(entry);
    }

    vfile.close();
    std::cout << "[VectorStore] Loaded " << count << " vectors (dim=" << dim << ")" << std::endl;
    return true;
}

} // namespace fs
} // namespace ainos