#ifndef AINOS_AI_RUNTIME_FFI_H
#define AINOS_AI_RUNTIME_FFI_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// Ainos AI Runtime C FFI Wrapper
// ============================================================================
// These functions wrap the C++ IGGMLEngine, IONNXService, and IModelManager
// interfaces in C-compatible APIs for Rust FFI binding via `extern "C"`.

// Opaque handle types
typedef void* ainos_engine_t;
typedef void* ainos_model_manager_t;
typedef void* ainos_context_manager_t;

// Status codes matching ainos::ai::Status
typedef int32_t ainos_status_t;
#define AINOS_STATUS_OK                       0
#define AINOS_STATUS_ERROR_INVALID_PARAM      -1
#define AINOS_STATUS_ERROR_MODEL_NOT_FOUND    -2
#define AINOS_STATUS_ERROR_INFERENCE_FAILED   -3
#define AINOS_STATUS_ERROR_OUT_OF_MEMORY      -4
#define AINOS_STATUS_ERROR_DEVICE_NOT_AVAILABLE -5
#define AINOS_STATUS_ERROR_CONTEXT_OVERFLOW   -6
#define AINOS_STATUS_ERROR_SERIALIZATION_FAILED -7

// Device types
typedef int32_t ainos_device_t;
#define AINOS_DEVICE_CPU 0
#define AINOS_DEVICE_GPU 1
#define AINOS_DEVICE_NPU 2

// ============================================================================
// GGML Engine FFI
// ============================================================================

/// Create a new GGML inference engine instance.
/// Returns an opaque handle (NULL on failure).
ainos_engine_t ainos_engine_create(void);

/// Destroy a GGML engine instance.
void ainos_engine_destroy(ainos_engine_t engine);

/// Load a model from a GGUF file.
/// @param engine  Engine handle from ainos_engine_create()
/// @param model_path  Full path to the .gguf model file
/// @param model_id  Unique identifier for the model
/// @return AINOS_STATUS_OK on success, error code otherwise
ainos_status_t ainos_engine_load_model(ainos_engine_t engine,
                                       const char* model_path,
                                       const char* model_id);

/// Unload a model and free its resources.
/// @param engine  Engine handle
/// @param model_id  Model identifier matching ainos_engine_load_model()
/// @return AINOS_STATUS_OK on success, error code otherwise
ainos_status_t ainos_engine_unload_model(ainos_engine_t engine,
                                         const char* model_id);

/// Run inference synchronously.
/// The output string is allocated by the callee and must be freed with
/// ainos_engine_free_string().
/// @param engine  Engine handle
/// @param model_id  Target model identifier
/// @param prompt  Input text
/// @param output  Pointer to receive the output string (caller must free)
/// @param max_tokens  Maximum tokens to generate
/// @param temperature  Sampling temperature (0.0 - 2.0)
/// @param top_p  Nucleus sampling parameter (0.0 - 1.0)
/// @param top_k  Top-k sampling parameter
/// @param num_threads  Number of inference threads
/// @return AINOS_STATUS_OK on success, error code otherwise
ainos_status_t ainos_engine_inference(ainos_engine_t engine,
                                      const char* model_id,
                                      const char* prompt,
                                      char** output,
                                      int32_t max_tokens,
                                      float temperature,
                                      float top_p,
                                      int32_t top_k,
                                      int32_t num_threads);

/// Get model metadata.
/// @param engine  Engine handle
/// @param model_id  Target model identifier
/// @param out_model_path  Receives model file path (caller must free)
/// @param out_loaded_time  Receives load timestamp (nanoseconds since epoch)
/// @param out_memory_usage  Receives memory usage in bytes
/// @param out_device  Receives device type (ainos_device_t)
/// @return AINOS_STATUS_OK on success, error code otherwise
ainos_status_t ainos_engine_get_model_info(ainos_engine_t engine,
                                           const char* model_id,
                                           char** out_model_path,
                                           int64_t* out_loaded_time,
                                           size_t* out_memory_usage,
                                           ainos_device_t* out_device);

/// Free a string allocated by the engine.
void ainos_engine_free_string(char* s);

// ============================================================================
// ONNX Service FFI
// ============================================================================

/// Create a new ONNX Runtime service instance.
ainos_engine_t ainos_onnx_service_create(void);

/// Destroy an ONNX service instance.
void ainos_onnx_service_destroy(ainos_engine_t service);

/// Load an ONNX model.
ainos_status_t ainos_onnx_service_load_model(ainos_engine_t service,
                                             const char* model_path,
                                             const char* model_id);

/// Unload an ONNX model.
ainos_status_t ainos_onnx_service_unload_model(ainos_engine_t service,
                                               const char* model_id);

// ============================================================================
// Model Manager FFI
// ============================================================================

/// Create a model manager instance.
ainos_model_manager_t ainos_model_manager_create(void);

/// Destroy a model manager instance.
void ainos_model_manager_destroy(ainos_model_manager_t mgr);

/// Register a model with the manager.
ainos_status_t ainos_model_manager_register(ainos_model_manager_t mgr,
                                            const char* model_id,
                                            const char* model_path,
                                            const char* framework);

/// Unregister a model.
ainos_status_t ainos_model_manager_unregister(ainos_model_manager_t mgr,
                                              const char* model_id);

/// Load a registered model.
ainos_status_t ainos_model_manager_load(ainos_model_manager_t mgr,
                                        const char* model_id);

/// Unload a loaded model.
ainos_status_t ainos_model_manager_unload(ainos_model_manager_t mgr,
                                          const char* model_id);

/// Optimize memory by unloading idle models.
ainos_status_t ainos_model_manager_optimize_memory(ainos_model_manager_t mgr);

#ifdef __cplusplus
}
#endif

#endif // AINOS_AI_RUNTIME_FFI_H