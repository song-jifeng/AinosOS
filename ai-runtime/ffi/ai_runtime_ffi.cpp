// Ainos OS - AI Runtime C FFI Implementation
// Wraps C++ IGGMLEngine, IONNXService, IModelManager in C-compatible functions
// for Rust FFI binding via `extern "C"`.

#include "ainos/ai_runtime.h"
#include "ainos/ai_runtime_ffi.h"
#include <cstring>
#include <string>

// ============================================================================
// GGML Engine FFI
// ============================================================================

ainos_engine_t ainos_engine_create(void) {
    auto engine = ainos::ai::CreateGGMLEngine();
    if (!engine) return nullptr;
    // Transfer ownership to a raw pointer via shared_ptr
    auto* shared = new std::shared_ptr<ainos::ai::IGGMLEngine>(engine);
    return static_cast<ainos_engine_t>(shared);
}

void ainos_engine_destroy(ainos_engine_t engine) {
    if (!engine) return;
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IGGMLEngine>*>(engine);
    delete shared;
}

ainos_status_t ainos_engine_load_model(ainos_engine_t engine,
                                       const char* model_path,
                                       const char* model_id) {
    if (!engine || !model_path || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IGGMLEngine>*>(engine);
    auto status = (*shared)->LoadModel(model_path, model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_engine_unload_model(ainos_engine_t engine,
                                         const char* model_id) {
    if (!engine || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IGGMLEngine>*>(engine);
    auto status = (*shared)->UnloadModel(model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_engine_inference(ainos_engine_t engine,
                                      const char* model_id,
                                      const char* prompt,
                                      char** output,
                                      int32_t max_tokens,
                                      float temperature,
                                      float top_p,
                                      int32_t top_k,
                                      int32_t num_threads) {
    if (!engine || !model_id || !prompt || !output) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }

    auto* shared = static_cast<std::shared_ptr<ainos::ai::IGGMLEngine>*>(engine);

    ainos::ai::InferenceConfig config;
    config.max_tokens = max_tokens > 0 ? max_tokens : 512;
    config.temperature = temperature;
    config.top_p = top_p;
    config.top_k = top_k;
    config.num_threads = num_threads > 0 ? num_threads : 4;
    config.device = ainos::ai::DeviceType::CPU;
    config.use_cache = true;

    std::string result;
    auto status = (*shared)->Inference(model_id, prompt, result, config);
    if (status != ainos::ai::Status::OK) {
        return static_cast<ainos_status_t>(status);
    }

    *output = static_cast<char*>(std::malloc(result.size() + 1));
    if (!*output) {
        return AINOS_STATUS_ERROR_OUT_OF_MEMORY;
    }
    std::memcpy(*output, result.c_str(), result.size() + 1);
    return AINOS_STATUS_OK;
}

ainos_status_t ainos_engine_get_model_info(ainos_engine_t engine,
                                           const char* model_id,
                                           char** out_model_path,
                                           int64_t* out_loaded_time,
                                           size_t* out_memory_usage,
                                           ainos_device_t* out_device) {
    if (!engine || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }

    auto* shared = static_cast<std::shared_ptr<ainos::ai::IGGMLEngine>*>(engine);

    ainos::ai::ModelMetadata metadata;
    auto status = (*shared)->GetModelInfo(model_id, metadata);
    if (status != ainos::ai::Status::OK) {
        return static_cast<ainos_status_t>(status);
    }

    if (out_model_path) {
        *out_model_path = static_cast<char*>(std::malloc(metadata.model_path.size() + 1));
        if (*out_model_path) {
            std::memcpy(*out_model_path, metadata.model_path.c_str(), metadata.model_path.size() + 1);
        }
    }
    if (out_loaded_time) *out_loaded_time = metadata.loaded_time;
    if (out_memory_usage) *out_memory_usage = metadata.memory_usage;
    if (out_device) *out_device = static_cast<ainos_device_t>(metadata.device);

    return AINOS_STATUS_OK;
}

void ainos_engine_free_string(char* s) {
    std::free(s);
}

// ============================================================================
// ONNX Service FFI
// ============================================================================

ainos_engine_t ainos_onnx_service_create(void) {
    auto service = ainos::ai::CreateONNXService();
    if (!service) return nullptr;
    auto* shared = new std::shared_ptr<ainos::ai::IONNXService>(service);
    return static_cast<ainos_engine_t>(shared);
}

void ainos_onnx_service_destroy(ainos_engine_t service) {
    if (!service) return;
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IONNXService>*>(service);
    delete shared;
}

ainos_status_t ainos_onnx_service_load_model(ainos_engine_t service,
                                             const char* model_path,
                                             const char* model_id) {
    if (!service || !model_path || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IONNXService>*>(service);
    auto status = (*shared)->LoadModel(model_path, model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_onnx_service_unload_model(ainos_engine_t service,
                                               const char* model_id) {
    if (!service || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IONNXService>*>(service);
    auto status = (*shared)->UnloadModel(model_id);
    return static_cast<ainos_status_t>(status);
}

// ============================================================================
// Model Manager FFI
// ============================================================================

ainos_model_manager_t ainos_model_manager_create(void) {
    auto mgr = ainos::ai::CreateModelManager();
    if (!mgr) return nullptr;
    auto* shared = new std::shared_ptr<ainos::ai::IModelManager>(mgr);
    return static_cast<ainos_model_manager_t>(shared);
}

void ainos_model_manager_destroy(ainos_model_manager_t mgr) {
    if (!mgr) return;
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    delete shared;
}

ainos_status_t ainos_model_manager_register(ainos_model_manager_t mgr,
                                            const char* model_id,
                                            const char* model_path,
                                            const char* framework) {
    if (!mgr || !model_id || !model_path || !framework) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    auto status = (*shared)->RegisterModel(model_id, model_path, framework);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_model_manager_unregister(ainos_model_manager_t mgr,
                                              const char* model_id) {
    if (!mgr || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    auto status = (*shared)->UnregisterModel(model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_model_manager_load(ainos_model_manager_t mgr,
                                        const char* model_id) {
    if (!mgr || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    auto status = (*shared)->LoadModel(model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_model_manager_unload(ainos_model_manager_t mgr,
                                          const char* model_id) {
    if (!mgr || !model_id) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    auto status = (*shared)->UnloadModel(model_id);
    return static_cast<ainos_status_t>(status);
}

ainos_status_t ainos_model_manager_optimize_memory(ainos_model_manager_t mgr) {
    if (!mgr) {
        return AINOS_STATUS_ERROR_INVALID_PARAM;
    }
    auto* shared = static_cast<std::shared_ptr<ainos::ai::IModelManager>*>(mgr);
    auto status = (*shared)->OptimizeMemory();
    return static_cast<ainos_status_t>(status);
}