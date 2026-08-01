#include "ainos/ai_runtime.h"
#include <map>
#include <mutex>
#include <fstream>
#include <algorithm>
#include <chrono>

namespace ainos {
namespace ai {

struct ModelEntry {
    std::string model_id;
    std::string model_path;
    std::string framework;
    bool is_loaded;
    int64_t registered_time;
    int64_t last_access_time;
    size_t access_count;
    ModelMetadata metadata;
};

class ModelManager : public IModelManager {
private:
    std::map<std::string, ModelEntry> models_;
    std::shared_ptr<IGGMLEngine> ggml_engine_;
    std::shared_ptr<IONNXService> onnx_service_;
    std::mutex mutex_;
    size_t max_loaded_models_;
    size_t total_memory_limit_;
    size_t current_memory_usage_;

    Status EvictLRUModel() {
        if (models_.empty()) {
            return Status::OK;
        }

        // 找到最少访问且已加载的模型
        std::string lru_model_id;
        int64_t oldest_time = std::numeric_limits<int64_t>::max();
        
        for (const auto& entry : models_) {
            if (entry.second.is_loaded && entry.second.last_access_time < oldest_time) {
                oldest_time = entry.second.last_access_time;
                lru_model_id = entry.first;
            }
        }

        if (!lru_model_id.empty()) {
            return UnloadModel(lru_model_id);
        }

        return Status::OK;
    }

public:
    ModelManager() 
        : max_loaded_models_(10)
        , total_memory_limit_(8ULL * 1024 * 1024 * 1024) // 8GB
        , current_memory_usage_(0) {
        
        ggml_engine_ = CreateGGMLEngine();
        onnx_service_ = CreateONNXService();
    }

    Status RegisterModel(const std::string& model_id,
                        const std::string& model_path,
                        const std::string& framework) override {
        std::lock_guard<std::mutex> lock(mutex_);

        if (models_.find(model_id) != models_.end()) {
            return Status::OK; // Already registered
        }

        // 验证框架类型
        if (framework != "ggml" && framework != "onnx") {
            return Status::ERROR_INVALID_PARAM;
        }

        // 验证模型文件存在
        std::ifstream file(model_path);
        if (!file.good()) {
            return Status::ERROR_MODEL_NOT_FOUND;
        }

        ModelEntry entry;
        entry.model_id = model_id;
        entry.model_path = model_path;
        entry.framework = framework;
        entry.is_loaded = false;
        entry.registered_time = std::chrono::system_clock::now().time_since_epoch().count();
        entry.last_access_time = entry.registered_time;
        entry.access_count = 0;

        models_[model_id] = entry;
        return Status::OK;
    }

    Status UnregisterModel(const std::string& model_id) override {
        std::lock_guard<std::mutex> lock(mutex_);

        auto it = models_.find(model_id);
        if (it == models_.end()) {
            return Status::ERROR_MODEL_NOT_FOUND;
        }

        if (it->second.is_loaded) {
            auto status = UnloadModel(model_id);
            if (status != Status::OK) {
                return status;
            }
        }

        models_.erase(it);
        return Status::OK;
    }

    Status LoadModel(const std::string& model_id) override {
        std::lock_guard<std::mutex> lock(mutex_);

        auto it = models_.find(model_id);
        if (it == models_.end()) {
            return Status::ERROR_MODEL_NOT_FOUND;
        }

        if (it->second.is_loaded) {
            it->second.last_access_time = std::chrono::system_clock::now().time_since_epoch().count();
            return Status::OK;
        }

        // 检查内存限制，必要时驱逐模型
        while (current_memory_usage_ > total_memory_limit_ * 0.8) {
            auto status = EvictLRUModel();
            if (status != Status::OK) {
                break;
            }
        }

        Status status;
        if (it->second.framework == "ggml") {
            status = ggml_engine_->LoadModel(it->second.model_path, model_id);
            if (status == Status::OK) {
                ggml_engine_->GetModelInfo(model_id, it->second.metadata);
            }
        } else if (it->second.framework == "onnx") {
            status = onnx_service_->LoadModel(it->second.model_path, model_id);
            if (status == Status::OK) {
                onnx_service_->GetModelInfo(model_id, it->second.metadata);
            }
        } else {
            return Status::ERROR_INVALID_PARAM;
        }

        if (status == Status::OK) {
            it->second.is_loaded = true;
            it->second.last_access_time = std::chrono::system_clock::now().time_since_epoch().count();
            it->second.access_count++;
            current_memory_usage_ += it->second.metadata.memory_usage;
        }

        return status;
    }

    Status UnloadModel(const std::string& model_id) override {
        auto it = models_.find(model_id);
        if (it == models_.end()) {
            return Status::ERROR_MODEL_NOT_FOUND;
        }

        if (!it->second.is_loaded) {
            return Status::OK;
        }

        Status status;
        if (it->second.framework == "ggml") {
            status = ggml_engine_->UnloadModel(model_id);
        } else if (it->second.framework == "onnx") {
            status = onnx_service_->UnloadModel(model_id);
        }

        if (status == Status::OK) {
            current_memory_usage_ -= it->second.metadata.memory_usage;
            it->second.is_loaded = false;
        }

        return status;
    }

    Status ListModels(std::vector<ModelMetadata>& models) override {
        std::lock_guard<std::mutex> lock(mutex_);

        models.clear();
        for (const auto& entry : models_) {
            if (entry.second.is_loaded) {
                models.push_back(entry.second.metadata);
            } else {
                ModelMetadata meta;
                meta.model_id = entry.second.model_id;
                meta.model_path = entry.second.model_path;
                meta.framework = entry.second.framework;
                meta.loaded_time = 0;
                meta.memory_usage = 0;
                meta.device = DeviceType::CPU;
                models.push_back(meta);
            }
        }

        return Status::OK;
    }

    Status GetModelMetadata(const std::string& model_id, ModelMetadata& metadata) override {
        std::lock_guard<std::mutex> lock(mutex_);

        auto it = models_.find(model_id);
        if (it == models_.end()) {
            return Status::ERROR_MODEL_NOT_FOUND;
        }

        if (it->second.is_loaded) {
            metadata = it->second.metadata;
        } else {
            metadata.model_id = it->second.model_id;
            metadata.model_path = it->second.model_path;
            metadata.framework = it->second.framework;
            metadata.loaded_time = 0;
            metadata.memory_usage = 0;
            metadata.device = DeviceType::CPU;
        }

        return Status::OK;
    }

    Status OptimizeMemory() override {
        std::lock_guard<std::mutex> lock(mutex_);

        // 卸载长时间未访问的模型
        int64_t current_time = std::chrono::system_clock::now().time_since_epoch().count();
        int64_t idle_threshold = 3600LL * 1000 * 1000 * 1000; // 1小时

        std::vector<std::string> to_unload;
        for (const auto& entry : models_) {
            if (entry.second.is_loaded && 
                (current_time - entry.second.last_access_time) > idle_threshold) {
                to_unload.push_back(entry.first);
            }
        }

        for (const auto& model_id : to_unload) {
            UnloadModel(model_id);
        }

        return Status::OK;
    }
};

std::shared_ptr<IModelManager> CreateModelManager() {
    return std::make_shared<ModelManager>();
}

} // namespace ai
} // namespace ainos