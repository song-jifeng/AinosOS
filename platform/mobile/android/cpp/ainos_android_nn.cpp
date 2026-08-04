/**
 * ainos_android_nn.cpp
 * Android NNAPI integration for Ainos AI inference
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos_mobile_common.h"
#include <android/log.h>
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>

#define LOG_TAG "AinosNN"

/*============================================================================
 * NNAPI Dynamic Loading
 *============================================================================*/

// NNAPI function pointer types
typedef struct {
    void* lib_handle;
    bool available;
    int32_t api_level;
    char error_message[256];
} ainos_nn_api_state_t;

static ainos_nn_api_state_t g_nn_state;

/*============================================================================
 * NNAPI Types (from <android/neuralnetworks.h>)
 *============================================================================*/

typedef int32_t ANeuralNetworksOperationType;
typedef int32_t ANeuralNetworksOperandType;
typedef int32_t ANeuralNetworksFuseCode;

typedef struct ANeuralNetworksMemory ANeuralNetworksMemory;
typedef struct ANeuralNetworksModel ANeuralNetworksModel;
typedef struct ANeuralNetworksCompilation ANeuralNetworksCompilation;
typedef struct ANeuralNetworksExecution ANeuralNetworksExecution;
typedef struct ANeuralNetworksBurst ANeuralNetworksBurst;
typedef struct ANeuralNetworksDevice ANeuralNetworksDevice;

/*============================================================================
 * NNAPI Function Pointers
 *============================================================================*/

typedef int (*ANeuralNetworksMemory_createFromFd_fn)(
    size_t size, int protect, int fd, size_t offset,
    ANeuralNetworksMemory** memory);

typedef void (*ANeuralNetworksMemory_free_fn)(ANeuralNetworksMemory* memory);

typedef int (*ANeuralNetworksModel_create_fn)(ANeuralNetworksModel** model);

typedef void (*ANeuralNetworksModel_free_fn)(ANeuralNetworksModel* model);

typedef int (*ANeuralNetworksModel_finish_fn)(ANeuralNetworksModel* model);

typedef int (*ANeuralNetworksModel_addOperand_fn)(
    ANeuralNetworksModel* model,
    const ANeuralNetworksOperandType* type);

typedef int (*ANeuralNetworksModel_setOperandValue_fn)(
    ANeuralNetworksModel* model,
    int32_t index,
    const void* buffer,
    size_t length);

typedef int (*ANeuralNetworksModel_addOperation_fn)(
    ANeuralNetworksModel* model,
    ANeuralNetworksOperationType type,
    uint32_t inputCount,
    const uint32_t* inputs,
    uint32_t outputCount,
    const uint32_t* outputs);

typedef int (*ANeuralNetworksModel_identifyInputsAndOutputs_fn)(
    ANeuralNetworksModel* model,
    uint32_t inputCount,
    const uint32_t* inputs,
    uint32_t outputCount,
    const uint32_t* outputs);

typedef int (*ANeuralNetworksCompilation_create_fn)(
    ANeuralNetworksModel* model,
    ANeuralNetworksCompilation** compilation);

typedef void (*ANeuralNetworksCompilation_free_fn)(
    ANeuralNetworksCompilation* compilation);

typedef int (*ANeuralNetworksCompilation_setPreference_fn)(
    ANeuralNetworksCompilation* compilation,
    int32_t preference);

typedef int (*ANeuralNetworksCompilation_finish_fn)(
    ANeuralNetworksCompilation* compilation);

typedef int (*ANeuralNetworksExecution_create_fn)(
    ANeuralNetworksCompilation* compilation,
    ANeuralNetworksExecution** execution);

typedef void (*ANeuralNetworksExecution_free_fn)(
    ANeuralNetworksExecution* execution);

typedef int (*ANeuralNetworksExecution_setInput_fn)(
    ANeuralNetworksExecution* execution,
    int32_t index,
    const void* buffer,
    size_t length);

typedef int (*ANeuralNetworksExecution_setOutput_fn)(
    ANeuralNetworksExecution* execution,
    int32_t index,
    void* buffer,
    size_t length);

typedef int (*ANeuralNetworksExecution_compute_fn)(
    ANeuralNetworksExecution* execution);

typedef int (*ANeuralNetworksExecution_startCompute_fn)(
    ANeuralNetworksExecution* execution,
    void** sync_fence);

typedef int (*ANeuralNetworks_getDeviceCount_fn)(uint32_t* numDevices);

typedef int (*ANeuralNetworks_getDevice_fn)(
    uint32_t devIndex, ANeuralNetworksDevice** device);

typedef int (*ANeuralNetworksDevice_getName_fn)(
    const ANeuralNetworksDevice* device, const char** name);

typedef int (*ANeuralNetworksDevice_getType_fn)(
    const ANeuralNetworksDevice* device, int32_t* type);

typedef int (*ANeuralNetworksDevice_getVersion_fn)(
    const ANeuralNetworksDevice* device, const char* version);

typedef int (*ANeuralNetworksCompilation_setCaching_fn)(
    ANeuralNetworksCompilation* compilation,
    const char* cacheDir,
    const uint8_t* token);

// Function pointer storage
static ANeuralNetworksMemory_createFromFd_fn      ANeuralNetworksMemory_createFromFd = NULL;
static ANeuralNetworksMemory_free_fn               ANeuralNetworksMemory_free = NULL;
static ANeuralNetworksModel_create_fn              ANeuralNetworksModel_create = NULL;
static ANeuralNetworksModel_free_fn                ANeuralNetworksModel_free = NULL;
static ANeuralNetworksModel_finish_fn              ANeuralNetworksModel_finish = NULL;
static ANeuralNetworksModel_addOperand_fn          ANeuralNetworksModel_addOperand = NULL;
static ANeuralNetworksModel_setOperandValue_fn     ANeuralNetworksModel_setOperandValue = NULL;
static ANeuralNetworksModel_addOperation_fn        ANeuralNetworksModel_addOperation = NULL;
static ANeuralNetworksModel_identifyInputsAndOutputs_fn ANeuralNetworksModel_identifyInputsAndOutputs = NULL;
static ANeuralNetworksCompilation_create_fn        ANeuralNetworksCompilation_create = NULL;
static ANeuralNetworksCompilation_free_fn          ANeuralNetworksCompilation_free = NULL;
static ANeuralNetworksCompilation_setPreference_fn ANeuralNetworksCompilation_setPreference = NULL;
static ANeuralNetworksCompilation_finish_fn        ANeuralNetworksCompilation_finish = NULL;
static ANeuralNetworksExecution_create_fn          ANeuralNetworksExecution_create = NULL;
static ANeuralNetworksExecution_free_fn            ANeuralNetworksExecution_free = NULL;
static ANeuralNetworksExecution_setInput_fn        ANeuralNetworksExecution_setInput = NULL;
static ANeuralNetworksExecution_setOutput_fn       ANeuralNetworksExecution_setOutput = NULL;
static ANeuralNetworksExecution_compute_fn         ANeuralNetworksExecution_compute = NULL;
static ANeuralNetworksExecution_startCompute_fn    ANeuralNetworksExecution_startCompute = NULL;
static ANeuralNetworks_getDeviceCount_fn           ANeuralNetworks_getDeviceCount = NULL;
static ANeuralNetworks_getDevice_fn                ANeuralNetworks_getDevice = NULL;
static ANeuralNetworksDevice_getName_fn            ANeuralNetworksDevice_getName = NULL;
static ANeuralNetworksDevice_getType_fn            ANeuralNetworksDevice_getType = NULL;
static ANeuralNetworksDevice_getVersion_fn         ANeuralNetworksDevice_getVersion = NULL;
static ANeuralNetworksCompilation_setCaching_fn    ANeuralNetworksCompilation_setCaching = NULL;

/*============================================================================
 * NNAPI Delegate State
 *============================================================================*/

typedef struct {
    ANeuralNetworksModel* model;
    ANeuralNetworksCompilation* compilation;
    ANeuralNetworksExecution* execution;
    ANeuralNetworksDevice* device;
    int32_t device_type;
    char device_name[128];
    bool compiled;
    bool created;
    uint32_t input_count;
    uint32_t output_count;
    uint32_t* input_indices;
    uint32_t* output_indices;
    void* input_buffer;
    size_t input_size;
    void* output_buffer;
    size_t output_size;
    pthread_mutex_t lock;
} ainos_nn_delegate_t;

static ainos_nn_delegate_t g_nn_delegate;

/*============================================================================
 * NNAPI Initialization
 *============================================================================*/

ainos_status_t ainos_nn_init(void)
{
    memset(&g_nn_state, 0, sizeof(g_nn_state));
    memset(&g_nn_delegate, 0, sizeof(g_nn_delegate));
    pthread_mutex_init(&g_nn_delegate.lock, NULL);

    // Try to load NNAPI library
    g_nn_state.lib_handle = dlopen("libneuralnetworks.so", RTLD_LAZY | RTLD_LOCAL);
    if (!g_nn_state.lib_handle) {
        // Try alternative name
        g_nn_state.lib_handle = dlopen("libneuralnetworks_purefunctor.so", RTLD_LAZY | RTLD_LOCAL);
    }

    if (!g_nn_state.lib_handle) {
        g_nn_state.available = false;
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "NNAPI library not available: %s", dlerror());
        __android_log_print(ANDROID_LOG_WARN, LOG_TAG, "%s", g_nn_state.error_message);
        return AINOS_ERROR_NOT_SUPPORTED;
    }

    // Load all function pointers
    #define LOAD_FN(name) \
        do { \
            name##_fn fn = (name##_fn)dlsym(g_nn_state.lib_handle, #name); \
            if (fn) { \
                name = fn; \
            } else { \
                __android_log_print(ANDROID_LOG_WARN, LOG_TAG, \
                                    "Failed to load NNAPI function: %s", #name); \
            } \
        } while(0)

    LOAD_FN(ANeuralNetworksMemory_createFromFd);
    LOAD_FN(ANeuralNetworksMemory_free);
    LOAD_FN(ANeuralNetworksModel_create);
    LOAD_FN(ANeuralNetworksModel_free);
    LOAD_FN(ANeuralNetworksModel_finish);
    LOAD_FN(ANeuralNetworksModel_addOperand);
    LOAD_FN(ANeuralNetworksModel_setOperandValue);
    LOAD_FN(ANeuralNetworksModel_addOperation);
    LOAD_FN(ANeuralNetworksModel_identifyInputsAndOutputs);
    LOAD_FN(ANeuralNetworksCompilation_create);
    LOAD_FN(ANeuralNetworksCompilation_free);
    LOAD_FN(ANeuralNetworksCompilation_setPreference);
    LOAD_FN(ANeuralNetworksCompilation_finish);
    LOAD_FN(ANeuralNetworksExecution_create);
    LOAD_FN(ANeuralNetworksExecution_free);
    LOAD_FN(ANeuralNetworksExecution_setInput);
    LOAD_FN(ANeuralNetworksExecution_setOutput);
    LOAD_FN(ANeuralNetworksExecution_compute);
    LOAD_FN(ANeuralNetworksExecution_startCompute);
    LOAD_FN(ANeuralNetworks_getDeviceCount);
    LOAD_FN(ANeuralNetworks_getDevice);
    LOAD_FN(ANeuralNetworksDevice_getName);
    LOAD_FN(ANeuralNetworksDevice_getType);
    LOAD_FN(ANeuralNetworksDevice_getVersion);
    LOAD_FN(ANeuralNetworksCompilation_setCaching);

    g_nn_state.available = true;
    g_nn_state.api_level = 29; // Android 10

    // Enumerate devices
    if (ANeuralNetworks_getDeviceCount) {
        uint32_t device_count = 0;
        int result = ANeuralNetworks_getDeviceCount(&device_count);
        if (result == 0 && device_count > 0) {
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                "NNAPI available with %u devices", device_count);

            for (uint32_t i = 0; i < device_count; i++) {
                ANeuralNetworksDevice* device = NULL;
                if (ANeuralNetworks_getDevice(i, &device) == 0 && device) {
                    const char* name = NULL;
                    int32_t type = 0;
                    ANeuralNetworksDevice_getName(device, &name);
                    ANeuralNetworksDevice_getType(device, &type);

                    const char* type_str = "UNKNOWN";
                    switch (type) {
                        case 0: type_str = "CPU"; break;
                        case 1: type_str = "GPU"; break;
                        case 2: type_str = "ACCELERATOR"; break;
                        case 3: type_str = "OTHER"; break;
                    }

                    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                        "  Device %u: %s (type=%s)", i,
                                        name ? name : "unknown", type_str);

                    // Use the first accelerator or GPU as preferred device
                    if (type == 2 || type == 1) {
                        if (!g_nn_delegate.device) {
                            g_nn_delegate.device = device;
                            g_nn_delegate.device_type = type;
                            if (name) strncpy(g_nn_delegate.device_name, name,
                                              sizeof(g_nn_delegate.device_name) - 1);
                        }
                    }
                }
            }
        }
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "NNAPI initialized: available=%d, devices=%s",
                        g_nn_state.available,
                        g_nn_delegate.device_name);

    return AINOS_OK;
}

void ainos_nn_shutdown(void)
{
    pthread_mutex_lock(&g_nn_delegate.lock);

    if (g_nn_delegate.execution) {
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
    }
    if (g_nn_delegate.compilation) {
        ANeuralNetworksCompilation_free(g_nn_delegate.compilation);
        g_nn_delegate.compilation = NULL;
    }
    if (g_nn_delegate.model) {
        ANeuralNetworksModel_free(g_nn_delegate.model);
        g_nn_delegate.model = NULL;
    }
    if (g_nn_delegate.input_buffer) {
        free(g_nn_delegate.input_buffer);
        g_nn_delegate.input_buffer = NULL;
    }
    if (g_nn_delegate.output_buffer) {
        free(g_nn_delegate.output_buffer);
        g_nn_delegate.output_buffer = NULL;
    }
    if (g_nn_delegate.input_indices) {
        free(g_nn_delegate.input_indices);
        g_nn_delegate.input_indices = NULL;
    }
    if (g_nn_delegate.output_indices) {
        free(g_nn_delegate.output_indices);
        g_nn_delegate.output_indices = NULL;
    }

    g_nn_delegate.compiled = false;
    g_nn_delegate.created = false;

    pthread_mutex_unlock(&g_nn_delegate.lock);

    if (g_nn_state.lib_handle) {
        dlclose(g_nn_state.lib_handle);
        g_nn_state.lib_handle = NULL;
    }

    g_nn_state.available = false;
    pthread_mutex_destroy(&g_nn_delegate.lock);

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "NNAPI shutdown complete");
}

bool ainos_nn_is_available(void)
{
    return g_nn_state.available;
}

/*============================================================================
 * NNAPI Model Compilation
 *============================================================================*/

ainos_status_t ainos_nn_compile_model(
    const void* model_data,
    size_t model_size,
    int32_t preference)
{
    if (!model_data || model_size == 0) return AINOS_ERROR_INVALID_PARAM;
    if (!g_nn_state.available) return AINOS_ERROR_NOT_SUPPORTED;

    pthread_mutex_lock(&g_nn_delegate.lock);

    // Clean up previous compilation
    if (g_nn_delegate.execution) {
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
    }
    if (g_nn_delegate.compilation) {
        ANeuralNetworksCompilation_free(g_nn_delegate.compilation);
        g_nn_delegate.compilation = NULL;
    }
    if (g_nn_delegate.model) {
        ANeuralNetworksModel_free(g_nn_delegate.model);
        g_nn_delegate.model = NULL;
    }

    // Create model
    int result = ANeuralNetworksModel_create(&g_nn_delegate.model);
    if (result != 0 || !g_nn_delegate.model) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to create NNAPI model: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_MODEL_LOAD_FAILED;
    }

    // For actual TFLite models, we'd parse the flatbuffer and add operations.
    // Here we set up a simple passthrough model as a placeholder.
    // In production, the TFLite delegate handles this.

    // Finish model
    result = ANeuralNetworksModel_finish(g_nn_delegate.model);
    if (result != 0) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to finish NNAPI model: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksModel_free(g_nn_delegate.model);
        g_nn_delegate.model = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_MODEL_LOAD_FAILED;
    }

    // Create compilation
    result = ANeuralNetworksCompilation_create(g_nn_delegate.model, &g_nn_delegate.compilation);
    if (result != 0 || !g_nn_delegate.compilation) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to create NNAPI compilation: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksModel_free(g_nn_delegate.model);
        g_nn_delegate.model = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_MODEL_LOAD_FAILED;
    }

    // Set compilation preference
    if (ANeuralNetworksCompilation_setPreference) {
        ANeuralNetworksCompilation_setPreference(g_nn_delegate.compilation, preference);
    }

    // Set preferred device if available
    if (g_nn_delegate.device && ANeuralNetworksCompilation_setCaching) {
        // Note: In production, use ANNeuralNetworksCompilation_setDevice
        // For API 29+, we can set the device
    }

    // Finish compilation
    result = ANeuralNetworksCompilation_finish(g_nn_delegate.compilation);
    if (result != 0) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to finish NNAPI compilation: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksCompilation_free(g_nn_delegate.compilation);
        g_nn_delegate.compilation = NULL;
        ANeuralNetworksModel_free(g_nn_delegate.model);
        g_nn_delegate.model = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_MODEL_LOAD_FAILED;
    }

    g_nn_delegate.compiled = true;

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "NNAPI model compiled successfully (size=%zu)", model_size);

    pthread_mutex_unlock(&g_nn_delegate.lock);
    return AINOS_OK;
}

/*============================================================================
 * NNAPI Inference Execution
 *============================================================================*/

ainos_status_t ainos_nn_execute(
    const void* input_data,
    size_t input_size,
    void* output_data,
    size_t output_size)
{
    if (!input_data || !output_data) return AINOS_ERROR_INVALID_PARAM;
    if (!g_nn_state.available) return AINOS_ERROR_NOT_SUPPORTED;

    pthread_mutex_lock(&g_nn_delegate.lock);

    if (!g_nn_delegate.compiled) {
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_MODEL_LOAD_FAILED;
    }

    // Create execution
    if (g_nn_delegate.execution) {
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
    }

    int result = ANeuralNetworksExecution_create(
        g_nn_delegate.compilation, &g_nn_delegate.execution);
    if (result != 0 || !g_nn_delegate.execution) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to create NNAPI execution: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_INFERENCE_FAILED;
    }

    // Set input
    result = ANeuralNetworksExecution_setInput(
        g_nn_delegate.execution, 0, input_data, input_size);
    if (result != 0) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to set NNAPI input: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_INFERENCE_FAILED;
    }

    // Set output
    result = ANeuralNetworksExecution_setOutput(
        g_nn_delegate.execution, 0, output_data, output_size);
    if (result != 0) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "Failed to set NNAPI output: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_INFERENCE_FAILED;
    }

    // Compute
    result = ANeuralNetworksExecution_compute(g_nn_delegate.execution);
    if (result != 0) {
        snprintf(g_nn_state.error_message, sizeof(g_nn_state.error_message),
                 "NNAPI execution failed: %d", result);
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, "%s", g_nn_state.error_message);
        ANeuralNetworksExecution_free(g_nn_delegate.execution);
        g_nn_delegate.execution = NULL;
        pthread_mutex_unlock(&g_nn_delegate.lock);
        return AINOS_ERROR_INFERENCE_FAILED;
    }

    pthread_mutex_unlock(&g_nn_delegate.lock);
    return AINOS_OK;
}

/*============================================================================
 * NNAPI Delegate Configuration
 *============================================================================*/

void ainos_nn_get_delegate_options(char* buffer, size_t buffer_size)
{
    if (!buffer) return;

    snprintf(buffer, buffer_size,
             "{\"available\":%s,\"api_level\":%d,\"device\":\"%s\",\"device_type\":%d}",
             g_nn_state.available ? "true" : "false",
             g_nn_state.api_level,
             g_nn_delegate.device_name,
             g_nn_delegate.device_type);
}

bool ainos_nn_has_accelerator(void)
{
    return g_nn_state.available && g_nn_delegate.device != NULL &&
           g_nn_delegate.device_type == 2; // ACCELERATOR
}

bool ainos_nn_has_gpu(void)
{
    return g_nn_state.available && g_nn_delegate.device != NULL &&
           g_nn_delegate.device_type == 1; // GPU
}

/*============================================================================
 * GPU Delegate (for TFLite GPU)
 *============================================================================*/

typedef struct {
    void* lib_handle;
    bool available;
} ainos_gpu_delegate_state_t;

static ainos_gpu_delegate_state_t g_gpu_delegate;

// TFLite GPU delegate function types
typedef void* (*TfLiteGpuDelegateV2Create_fn)(const void* options);
typedef void (*TfLiteGpuDelegateV2Delete_fn)(void* delegate);
typedef int (*TfLiteGpuDelegateV2Bind_fn)(void* delegate, void* interpreter);

ainos_status_t ainos_gpu_delegate_init(void)
{
    memset(&g_gpu_delegate, 0, sizeof(g_gpu_delegate));

    // Try to load TFLite GPU delegate library
    g_gpu_delegate.lib_handle = dlopen("libgpu_delegate.so", RTLD_LAZY | RTLD_LOCAL);
    if (!g_gpu_delegate.lib_handle) {
        g_gpu_delegate.lib_handle = dlopen("libtensorflowlite_gpu_jni.so",
                                            RTLD_LAZY | RTLD_LOCAL);
    }

    if (!g_gpu_delegate.lib_handle) {
        __android_log_print(ANDROID_LOG_WARN, LOG_TAG,
                            "GPU delegate library not available");
        g_gpu_delegate.available = false;
        return AINOS_ERROR_NOT_SUPPORTED;
    }

    g_gpu_delegate.available = true;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "GPU delegate initialized successfully");
    return AINOS_OK;
}

void ainos_gpu_delegate_shutdown(void)
{
    if (g_gpu_delegate.lib_handle) {
        dlclose(g_gpu_delegate.lib_handle);
        g_gpu_delegate.lib_handle = NULL;
    }
    g_gpu_delegate.available = false;
}

bool ainos_gpu_delegate_is_available(void)
{
    return g_gpu_delegate.available;
}

/*============================================================================
 * XNNPACK Delegate
 *============================================================================*/

typedef struct {
    void* lib_handle;
    bool available;
} ainos_xnnpack_state_t;

static ainos_xnnpack_state_t g_xnnpack;

ainos_status_t ainos_xnnpack_init(void)
{
    memset(&g_xnnpack, 0, sizeof(g_xnnpack));

    g_xnnpack.lib_handle = dlopen("libXNNPACK.so", RTLD_LAZY | RTLD_LOCAL);
    if (!g_xnnpack.lib_handle) {
        g_xnnpack.lib_handle = dlopen("libxnnpack_delegate.so", RTLD_LAZY | RTLD_LOCAL);
    }

    if (!g_xnnpack.lib_handle) {
        g_xnnpack.available = false;
        return AINOS_ERROR_NOT_SUPPORTED;
    }

    g_xnnpack.available = true;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "XNNPACK initialized");
    return AINOS_OK;
}

void ainos_xnnpack_shutdown(void)
{
    if (g_xnnpack.lib_handle) {
        dlclose(g_xnnpack.lib_handle);
        g_xnnpack.lib_handle = NULL;
    }
    g_xnnpack.available = false;
}

/*============================================================================
 * Backend Selection
 *============================================================================*/

ainos_inference_backend_t ainos_nn_select_backend(void)
{
    // Select best available backend
    if (ainos_nn_has_accelerator()) {
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                            "Selected NNAPI accelerator backend");
        return AINOS_INFERENCE_BACKEND_NNAPI;
    }

    if (ainos_gpu_delegate_is_available()) {
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                            "Selected GPU delegate backend");
        return AINOS_INFERENCE_BACKEND_GPU;
    }

    if (ainos_nn_has_gpu()) {
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                            "Selected NNAPI GPU backend");
        return AINOS_INFERENCE_BACKEND_NNAPI;
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Selected CPU backend");
    return AINOS_INFERENCE_BACKEND_CPU;
}

const char* ainos_nn_get_last_error(void)
{
    return g_nn_state.error_message;
}