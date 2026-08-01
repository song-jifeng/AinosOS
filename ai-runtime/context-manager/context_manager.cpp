// context-manager/context_manager.cpp
// Ainos OS 上下文管理子系统
// NOTE: 此文件由 AI 生成，内容不完整，需要后续完善

#include "ainos/ai_runtime.h"
#include <map>
#include <mutex>
#include <fstream>
#include <chrono>
#include <cstring>
#include <limits>

namespace ainos {
namespace ai {

struct Context {
    std::string context_id;
    std::string model_id;
    std::vector<int32_t> tokens;
    size_t max_tokens;
    int64_t created_time;
    int64_t last_access_time;

    // KV缓存（简化版）
    std::vector<float> key_cache;
    std::vector<float> value_cache;
};

class ContextManager : public IContextManager {
private:
    std::map<std::string, Context> contexts_;
    std::mutex mutex_;
    size_t max_contexts_;
    std::string cache_directory_;

    Status EvictOldestContext() {
        if (contexts_.empty()) {
            return Status::OK;
        }
        std::string oldest_id;
        int64_t oldest_time = std::numeric_limits<int64_t>::max();
        for (const auto& entry : contexts_) {
            if (entry.second.last_access_time < oldest_time) {
                oldest_time = entry.second.last_access_time;
                oldest_id = entry.first;
            }
        }
        if (!oldest_id.empty()) {
            return DestroyContext(oldest_id);
        }
        return Status::OK;
    }

    std::string GetCachePath(const std::string& context_id) {
        return cache_directory_ + "/" + context_id + ".ctx";
    }

public:
    ContextManager()
        : max_contexts_(100)
        , cache_directory_("./context_cache") {}

    Status CreateContext(const std::string& model_id,
                         const std::string& context_id,
                         size_t max_tokens) override {
        std::lock_guard<std::mutex> lock(mutex_);

        if (contexts_.size() >= max_contexts_) {
            EvictOldestContext();
        }

        auto now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();

        Context ctx;
        ctx.context_id = context_id;
        ctx.model_id = model_id;
        ctx.max_tokens = max_tokens;
        ctx.created_time = now;
        ctx.last_access_time = now;

        contexts_[context_id] = ctx;
        return Status::OK;
    }

    Status DestroyContext(const std::string& context_id) override {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = contexts_.find(context_id);
        if (it == contexts_.end()) {
            return Status::ERROR_INVALID_PARAM;
        }
        contexts_.erase(it);
        return Status::OK;
    }

    Status UpdateContext(const std::string& context_id,
                         const std::vector<int32_t>& tokens) override {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = contexts_.find(context_id);
        if (it == contexts_.end()) {
            return Status::ERROR_INVALID_PARAM;
        }
        it->second.tokens = tokens;
        it->second.last_access_time =
            std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
        return Status::OK;
    }

    Status GetContextInfo(const std::string& context_id, ContextInfo& info) override {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = contexts_.find(context_id);
        if (it == contexts_.end()) {
            return Status::ERROR_INVALID_PARAM;
        }
        const auto& ctx = it->second;
        info.context_id = ctx.context_id;
        info.model_id = ctx.model_id;
        info.token_count = ctx.tokens.size();
        info.max_tokens = ctx.max_tokens;
        info.created_time = ctx.created_time;
        info.last_access_time = ctx.last_access_time;
        return Status::OK;
    }

    Status ListContexts(std::vector<ContextInfo>& contexts) override {
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& entry : contexts_) {
            ContextInfo info;
            info.context_id = entry.second.context_id;
            info.model_id = entry.second.model_id;
            info.token_count = entry.second.tokens.size();
            info.max_tokens = entry.second.max_tokens;
            info.created_time = entry.second.created_time;
            info.last_access_time = entry.second.last_access_time;
            contexts.push_back(info);
        }
        return Status::OK;
    }

    Status ClearExpiredContexts(int64_t max_age_seconds) override {
        std::lock_guard<std::mutex> lock(mutex_);
        auto now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();

        auto it = contexts_.begin();
        while (it != contexts_.end()) {
            if (now - it->second.last_access_time > max_age_seconds) {
                it = contexts_.erase(it);
            } else {
                ++it;
            }
        }
        return Status::OK;
    }

    Status SaveContext(const std::string& context_id, const std::string& path) override {
        // TODO: 序列化并保存到文件
        return Status::OK;
    }

    Status LoadContext(const std::string& context_id, const std::string& path) override {
        // TODO: 从文件加载
        return Status::OK;
    }
};

std::shared_ptr<IContextManager> CreateContextManager() {
    return std::make_shared<ContextManager>();
}

} // namespace ai
} // namespace ainos