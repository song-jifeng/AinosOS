#ifndef AINOS_AI_RUNTIME_H
#define AINOS_AI_RUNTIME_H

#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <cstdint>

namespace ainos {
namespace ai {

// 版本信息
constexpr const char* AI_RUNTIME_VERSION = "1.0.0";

// 返回码
enum class Status {
    OK = 0,
    ERROR_INVALID_PARAM = -1,
    ERROR_MODEL_NOT_FOUND = -2,
    ERROR_INFERENCE_FAILED = -3,
    ERROR_OUT_OF_MEMORY = -4,
    ERROR_DEVICE_NOT_AVAILABLE = -5,
    ERROR_CONTEXT_OVERFLOW = -6,
    ERROR_SERIALIZATION_FAILED = -7
};

// 设备类型
enum class DeviceType {
    CPU = 0,
    GPU = 1,
    NPU = 2
};

// 数据类型
enum class DataType {
    FLOAT32 = 0,
    FLOAT16 = 1,
    INT8 = 2,
    INT32 = 3,
    INT64 = 4
};

// 张量结构
struct Tensor {
    std::string name;
    std::vector<int64_t> shape;
    DataType dtype;
    void* data;
    size_t size;
    
    Tensor() : data(nullptr), size(0), dtype(DataType::FLOAT32) {}
    ~Tensor() { if (data) free(data); }
};

// 模型元数据
struct ModelMetadata {
    std::string model_id;
    std::string model_path;
    std::string framework;  // "ggml" or "onnx"
    int64_t loaded_time;
    size_t memory_usage;
    DeviceType device;
};

// 推理配置
struct InferenceConfig {
    int max_tokens = 512;
    float temperature = 0.7f;
    float top_p = 0.9f;
    int top_k = 40;
    int num_threads = 4;
    DeviceType device = DeviceType::CPU;
    bool use_cache = true;
};

// 上下文信息
struct ContextInfo {
    std::string context_id;
    std::string model_id;
    size_t token_count;
    size_t max_tokens;
    int64_t created_time;
    int64_t last_access_time;
};

// 回调函数类型
using TokenCallback = std::function<void(const std::string& token)>;
using ProgressCallback = std::function<void(float progress)>;

// GGML引擎接口
class IGGMLEngine {
public:
    virtual ~IGGMLEngine() = default;
    
    virtual Status LoadModel(const std::string& model_path, const std::string& model_id) = 0;
    virtual Status UnloadModel(const std::string& model_id) = 0;
    virtual Status Inference(const std::string& model_id, 
                           const std::string& prompt,
                           std::string& output,
                           const InferenceConfig& config = InferenceConfig()) = 0;
    virtual Status InferenceStream(const std::string& model_id,
                                  const std::string& prompt,
                                  TokenCallback callback,
                                  const InferenceConfig& config = InferenceConfig()) = 0;
    virtual Status GetModelInfo(const std::string& model_id, ModelMetadata& metadata) = 0;
};

// ONNX服务接口
class IONNXService {
public:
    virtual ~IONNXService() = default;
    
    virtual Status LoadModel(const std::string& model_path, const std::string& model_id) = 0;
    virtual Status UnloadModel(const std::string& model_id) = 0;
    virtual Status Inference(const std::string& model_id,
                           const std::vector<Tensor>& inputs,
                           std::vector<Tensor>& outputs) = 0;
    virtual Status GetModelInfo(const std::string& model_id, ModelMetadata& metadata) = 0;
};

// 模型管理器接口
class IModelManager {
public:
    virtual ~IModelManager() = default;
    
    virtual Status RegisterModel(const std::string& model_id,
                                const std::string& model_path,
                                const std::string& framework) = 0;
    virtual Status UnregisterModel(const std::string& model_id) = 0;
    virtual Status LoadModel(const std::string& model_id) = 0;
    virtual Status UnloadModel(const std::string& model_id) = 0;
    virtual Status ListModels(std::vector<ModelMetadata>& models) = 0;
    virtual Status GetModelMetadata(const std::string& model_id, ModelMetadata& metadata) = 0;
    virtual Status OptimizeMemory() = 0;
};

// 上下文管理器接口
class IContextManager {
public:
    virtual ~IContextManager() = default;
    
    virtual Status CreateContext(const std::string& model_id,
                                const std::string& context_id,
                                size_t max_tokens = 4096) = 0;
    virtual Status DestroyContext(const std::string& context_id) = 0;
    virtual Status SaveContext(const std::string& context_id, const std::string& path) = 0;
    virtual Status LoadContext(const std::string& context_id, const std::string& path) = 0;
    virtual Status UpdateContext(const std::string& context_id,
                                const std::vector<int32_t>& tokens) = 0;
    virtual Status GetContextInfo(const std::string& context_id, ContextInfo& info) = 0;
    virtual Status ListContexts(std::vector<ContextInfo>& contexts) = 0;
    virtual Status ClearExpiredContexts(int64_t max_age_seconds) = 0;
};

// 工厂函数
std::shared_ptr<IGGMLEngine> CreateGGMLEngine();
std::shared_ptr<IONNXService> CreateONNXService();
std::shared_ptr<IModelManager> CreateModelManager();
std::shared_ptr<IContextManager> CreateContextManager();

} // namespace ai
} // namespace ainos

#endif // AINOS_AI_RUNTIME_H