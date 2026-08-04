/**
 * platform_mobile.h
 * Ainos Mobile Platform API - Unified interface for Android and iOS
 *
 * Copyright (c) Ainos 2026
 * All rights reserved.
 *
 * This header defines the common C API for the Ainos mobile platform support layer.
 * It provides abstractions for AI inference, thermal management, battery optimization,
 * permission handling, model management, and inter-process communication with the
 * AinosOS daemon.
 */

#ifndef AINOS_PLATFORM_MOBILE_H
#define AINOS_PLATFORM_MOBILE_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*============================================================================
 * Version Information
 *============================================================================*/
#define AINOS_PLATFORM_MOBILE_VERSION_MAJOR 1
#define AINOS_PLATFORM_MOBILE_VERSION_MINOR 0
#define AINOS_PLATFORM_MOBILE_VERSION_PATCH 0
#define AINOS_PLATFORM_MOBILE_VERSION      "1.0.0"

/*============================================================================
 * Platform Identification
 *============================================================================*/
typedef enum {
    AINOS_PLATFORM_UNKNOWN = 0,
    AINOS_PLATFORM_ANDROID,
    AINOS_PLATFORM_IOS
} ainos_platform_type_t;

AINOS_EXPORT ainos_platform_type_t ainos_platform_detect(void);

/*============================================================================
 * Error Codes
 *============================================================================*/
typedef enum {
    AINOS_OK                        = 0,
    AINOS_ERROR_GENERAL             = -1,
    AINOS_ERROR_INVALID_PARAM       = -2,
    AINOS_ERROR_OUT_OF_MEMORY       = -3,
    AINOS_ERROR_NOT_INITIALIZED     = -4,
    AINOS_ERROR_ALREADY_INITIALIZED = -5,
    AINOS_ERROR_TIMEOUT             = -6,
    AINOS_ERROR_NETWORK             = -7,
    AINOS_ERROR_PERMISSION_DENIED   = -8,
    AINOS_ERROR_THERMAL_THROTTLED   = -9,
    AINOS_ERROR_BATTERY_LOW         = -10,
    AINOS_ERROR_MODEL_NOT_FOUND     = -11,
    AINOS_ERROR_MODEL_LOAD_FAILED   = -12,
    AINOS_ERROR_MODEL_INVALID       = -13,
    AINOS_ERROR_INFERENCE_FAILED    = -14,
    AINOS_ERROR_DAEMON_UNREACHABLE  = -15,
    AINOS_ERROR_DAEMON_DISCONNECTED = -16,
    AINOS_ERROR_STREAM_BUSY         = -17,
    AINOS_ERROR_STREAM_CLOSED       = -18,
    AINOS_ERROR_NOT_SUPPORTED       = -19,
    AINOS_ERROR_BUSY                = -20,
    AINOS_ERROR_CANCELLED           = -21,
    AINOS_ERROR_STORAGE_FULL        = -22,
    AINOS_ERROR_UPDATE_AVAILABLE    = -23,
    AINOS_ERROR_NEEDS_REBOOT        = -24
} ainos_status_t;

/*============================================================================
 * Logging Levels
 *============================================================================*/
typedef enum {
    AINOS_LOG_VERBOSE = 0,
    AINOS_LOG_DEBUG   = 1,
    AINOS_LOG_INFO    = 2,
    AINOS_LOG_WARN    = 3,
    AINOS_LOG_ERROR   = 4,
    AINOS_LOG_FATAL   = 5,
    AINOS_LOG_NONE    = 6
} ainos_log_level_t;

typedef void (*ainos_log_callback_t)(ainos_log_level_t level, const char* tag, const char* message);

/*============================================================================
 * Initialization and Lifecycle
 *============================================================================*/

/**
 * Initialize the Ainos mobile platform.
 * Must be called before any other API function.
 *
 * @param app_name     Application name for identification
 * @param app_version  Application version string
 * @param log_callback Optional callback for log messages (can be NULL)
 * @return AINOS_OK on success, error code otherwise
 */
AINOS_EXPORT ainos_status_t ainos_platform_init(
    const char* app_name,
    const char* app_version,
    ainos_log_callback_t log_callback
);

/**
 * Shutdown the Ainos mobile platform.
 * Releases all resources, stops background services, and disconnects from daemon.
 */
AINOS_EXPORT void ainos_platform_shutdown(void);

/**
 * Check if the platform has been initialized.
 * @return true if initialized, false otherwise
 */
AINOS_EXPORT bool ainos_platform_is_initialized(void);

/**
 * Get the platform version string.
 * @return Version string (e.g., "1.0.0")
 */
AINOS_EXPORT const char* ainos_platform_version(void);

/*============================================================================
 * Thermal Management
 *============================================================================*/

typedef enum {
    AINOS_THERMAL_STATUS_NORMAL      = 0,
    AINOS_THERMAL_STATUS_WARM        = 1,
    AINOS_THERMAL_STATUS_HOT         = 2,
    AINOS_THERMAL_STATUS_CRITICAL    = 3,
    AINOS_THERMAL_STATUS_EMERGENCY   = 4,
    AINOS_THERMAL_STATUS_UNKNOWN     = 5
} ainos_thermal_status_t;

typedef enum {
    AINOS_THERMAL_THROTTLE_NONE      = 0,
    AINOS_THERMAL_THROTTLE_MILD      = 1,
    AINOS_THERMAL_THROTTLE_MODERATE  = 2,
    AINOS_THERMAL_THROTTLE_SEVERE    = 3,
    AINOS_THERMAL_THROTTLE_SHUTDOWN  = 4
} ainos_thermal_throttle_t;

/**
 * Get the current thermal status of the device.
 * @return Current thermal status
 */
AINOS_EXPORT ainos_thermal_status_t ainos_thermal_get_status(void);

/**
 * Get the current throttle level based on thermal conditions.
 * @return Current throttle level
 */
AINOS_EXPORT ainos_thermal_throttle_t ainos_thermal_get_throttle_level(void);

/**
 * Get the current CPU temperature in Celsius.
 * @param temperature Output parameter for temperature in Celsius
 * @return AINOS_OK on success, error code otherwise
 */
AINOS_EXPORT ainos_status_t ainos_thermal_get_cpu_temperature(float* temperature);

/**
 * Get the current battery temperature in Celsius.
 * @param temperature Output parameter for temperature in Celsius
 * @return AINOS_OK on success, error code otherwise
 */
AINOS_EXPORT ainos_status_t ainos_thermal_get_battery_temperature(float* temperature);

/**
 * Register a thermal status change callback.
 * @param callback Function to call when thermal status changes
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_thermal_register_callback(
    void (*callback)(ainos_thermal_status_t old_status, ainos_thermal_status_t new_status, void* user_data),
    void* user_data
);

/**
 * Unregister the thermal status change callback.
 */
AINOS_EXPORT void ainos_thermal_unregister_callback(void);

/**
 * Get recommended AI inference batch size based on current thermal conditions.
 * @return Recommended batch size (1-32)
 */
AINOS_EXPORT int ainos_thermal_get_recommended_batch_size(void);

/**
 * Check if inference should be throttled due to thermal conditions.
 * @return true if inference should be throttled
 */
AINOS_EXPORT bool ainos_thermal_should_throttle_inference(void);

/*============================================================================
 * Battery Management
 *============================================================================*/

typedef enum {
    AINOS_BATTERY_STATUS_UNKNOWN     = 0,
    AINOS_BATTERY_STATUS_CHARGING    = 1,
    AINOS_BATTERY_STATUS_DISCHARGING = 2,
    AINOS_BATTERY_STATUS_FULL        = 3,
    AINOS_BATTERY_STATUS_NOT_CHARGING = 4
} ainos_battery_status_t;

typedef enum {
    AINOS_POWER_MODE_NORMAL          = 0,
    AINOS_POWER_MODE_LOW_POWER       = 1,
    AINOS_POWER_MODE_ULTRA_SAVING    = 2,
    AINOS_POWER_MODE_PERFORMANCE     = 3
} ainos_power_mode_t;

/**
 * Get the current battery level (0-100).
 * @param level Output parameter for battery percentage
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_battery_get_level(int* level);

/**
 * Get the current battery status.
 * @return Battery status enum
 */
AINOS_EXPORT ainos_battery_status_t ainos_battery_get_status(void);

/**
 * Get the current power mode.
 * @return Power mode enum
 */
AINOS_EXPORT ainos_power_mode_t ainos_battery_get_power_mode(void);

/**
 * Check if low power mode is active.
 * @return true if low power mode is active
 */
AINOS_EXPORT bool ainos_battery_is_low_power_mode(void);

/**
 * Check if the device is currently charging.
 * @return true if charging
 */
AINOS_EXPORT bool ainos_battery_is_charging(void);

/**
 * Get estimated time remaining in minutes.
 * @param minutes Output parameter for estimated minutes remaining
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_battery_get_estimated_time(int* minutes);

/**
 * Register a battery state change callback.
 * @param callback Function to call when battery state changes
 * @param user_data User data passed to callback
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_battery_register_callback(
    void (*callback)(ainos_battery_status_t status, int level, void* user_data),
    void* user_data
);

/**
 * Unregister the battery state change callback.
 */
AINOS_EXPORT void ainos_battery_unregister_callback(void);

/**
 * Request a specific power mode.
 * @param mode Desired power mode
 * @return AINOS_OK on success, error if mode not available
 */
AINOS_EXPORT ainos_status_t ainos_battery_request_power_mode(ainos_power_mode_t mode);

/*============================================================================
 * Permission Management
 *============================================================================*/

typedef enum {
    AINOS_PERMISSION_CAMERA          = 0,
    AINOS_PERMISSION_MICROPHONE      = 1,
    AINOS_PERMISSION_STORAGE         = 2,
    AINOS_PERMISSION_NOTIFICATIONS   = 3,
    AINOS_PERMISSION_BACKGROUND_SERVICE = 4,
    AINOS_PERMISSION_NETWORK_STATE   = 5,
    AINOS_PERMISSION_BLUETOOTH       = 6,
    AINOS_PERMISSION_LOCATION        = 7,
    AINOS_PERMISSION_VIBRATE         = 8,
    AINOS_PERMISSION_WAKE_LOCK       = 9,
    AINOS_PERMISSION_FOREGROUND_SERVICE = 10,
    AINOS_PERMISSION_SCHEDULE_EXACT_ALARM = 11,
    AINOS_PERMISSION_POST_NOTIFICATIONS = 12,
    AINOS_PERMISSION_COUNT
} ainos_permission_t;

typedef enum {
    AINOS_PERMISSION_STATE_NOT_DETERMINED = 0,
    AINOS_PERMISSION_STATE_GRANTED        = 1,
    AINOS_PERMISSION_STATE_DENIED         = 2,
    AINOS_PERMISSION_STATE_RESTRICTED     = 3,
    AINOS_PERMISSION_STATE_DENIED_FOREVER = 4
} ainos_permission_state_t;

typedef void (*ainos_permission_callback_t)(ainos_permission_t permission, ainos_permission_state_t state, void* user_data);

/**
 * Check the current state of a permission.
 * @param permission The permission to check
 * @param state Output parameter for the permission state
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_permission_check(
    ainos_permission_t permission,
    ainos_permission_state_t* state
);

/**
 * Request a permission from the user.
 * @param permission The permission to request
 * @param callback   Callback invoked with the result
 * @param user_data  User data passed to callback
 * @return AINOS_OK if the request was initiated
 */
AINOS_EXPORT ainos_status_t ainos_permission_request(
    ainos_permission_t permission,
    ainos_permission_callback_t callback,
    void* user_data
);

/**
 * Request multiple permissions at once.
 * @param permissions Array of permissions to request
 * @param count       Number of permissions in the array
 * @param callback    Callback invoked with the result for each permission
 * @param user_data   User data passed to callback
 * @return AINOS_OK if the request was initiated
 */
AINOS_EXPORT ainos_status_t ainos_permission_request_multiple(
    const ainos_permission_t* permissions,
    size_t count,
    ainos_permission_callback_t callback,
    void* user_data
);

/**
 * Open the app's permission settings page.
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_permission_open_settings(void);

/**
 * Check if we should show a rationale for a permission.
 * @param permission The permission to check
 * @return true if rationale should be shown
 */
AINOS_EXPORT bool ainos_permission_should_show_rationale(ainos_permission_t permission);

/**
 * Get the display name for a permission.
 * @param permission The permission
 * @return Human-readable permission name (static string, do not free)
 */
AINOS_EXPORT const char* ainos_permission_get_name(ainos_permission_t permission);

/*============================================================================
 * Model Management
 *============================================================================*/

typedef enum {
    AINOS_MODEL_FORMAT_UNKNOWN       = 0,
    AINOS_MODEL_FORMAT_TFLITE        = 1,
    AINOS_MODEL_FORMAT_COREML        = 2,
    AINOS_MODEL_FORMAT_ONNX          = 3,
    AINOS_MODEL_FORMAT_SAFETENSORS   = 4
} ainos_model_format_t;

typedef enum {
    AINOS_MODEL_TYPE_UNKNOWN         = 0,
    AINOS_MODEL_TYPE_LLM             = 1,
    AINOS_MODEL_TYPE_VISION          = 2,
    AINOS_MODEL_TYPE_AUDIO           = 3,
    AINOS_MODEL_TYPE_EMBEDDING       = 4,
    AINOS_MODEL_TYPE_MULTIMODAL      = 5
} ainos_model_type_t;

typedef enum {
    AINOS_MODEL_STATE_NOT_DOWNLOADED  = 0,
    AINOS_MODEL_STATE_DOWNLOADING     = 1,
    AINOS_MODEL_STATE_DOWNLOADED      = 2,
    AINOS_MODEL_STATE_LOADING         = 3,
    AINOS_MODEL_STATE_LOADED          = 4,
    AINOS_MODEL_STATE_ERROR           = 5,
    AINOS_MODEL_STATE_OBSOLETE        = 6
} ainos_model_state_t;

typedef enum {
    AINOS_MODEL_PRECISION_FP32       = 0,
    AINOS_MODEL_PRECISION_FP16       = 1,
    AINOS_MODEL_PRECISION_INT8       = 2,
    AINOS_MODEL_PRECISION_INT4       = 3,
    AINOS_MODEL_PRECISION_MIXED      = 4
} ainos_model_precision_t;

typedef struct {
    char     model_id[128];
    char     model_name[256];
    char     model_version[64];
    ainos_model_format_t   format;
    ainos_model_type_t     type;
    ainos_model_precision_t precision;
    ainos_model_state_t    state;
    uint64_t file_size;
    uint64_t download_size;
    uint64_t download_progress;
    uint32_t parameter_count;
    uint32_t quantization_bits;
    float    model_size_mb;
    float    required_ram_mb;
    float    required_storage_mb;
    char     checksum_sha256[65];
    char     download_url[512];
    char     model_path[512];
    char     cache_path[512];
    int64_t  last_used_timestamp;
    int64_t  download_timestamp;
    bool     is_bundled;
    bool     requires_network;
    bool     is_encrypted;
} ainos_model_info_t;

typedef struct {
    char     model_id[128];
    ainos_model_state_t state;
    uint64_t progress;
    uint64_t total;
    float    speed_mbps;
    int      estimated_seconds_remaining;
    char     error_message[256];
} ainos_model_download_progress_t;

typedef void (*ainos_model_download_callback_t)(const ainos_model_download_progress_t* progress, void* user_data);
typedef void (*ainos_model_load_callback_t)(const char* model_id, ainos_status_t status, void* user_data);

/**
 * Initialize the model management subsystem.
 * @param cache_dir Directory for model caching
 * @param max_cache_size_mb Maximum cache size in MB
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_init(const char* cache_dir, uint32_t max_cache_size_mb);

/**
 * Get the list of available models.
 * @param models   Output array of model info (caller must free with ainos_model_free_list)
 * @param count    Output count of models
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_get_available(ainos_model_info_t** models, size_t* count);

/**
 * Get information about a specific model.
 * @param model_id The model identifier
 * @param info     Output model info (caller must free with ainos_model_free_info)
 * @return AINOS_OK on success, AINOS_ERROR_MODEL_NOT_FOUND if not found
 */
AINOS_EXPORT ainos_status_t ainos_model_get_info(const char* model_id, ainos_model_info_t* info);

/**
 * Start downloading a model.
 * @param model_id  The model identifier to download
 * @param callback  Progress callback (can be NULL)
 * @param user_data User data passed to callback
 * @return AINOS_OK if download started
 */
AINOS_EXPORT ainos_status_t ainos_model_download(
    const char* model_id,
    ainos_model_download_callback_t callback,
    void* user_data
);

/**
 * Cancel an ongoing model download.
 * @param model_id The model identifier
 * @return AINOS_OK if download was cancelled
 */
AINOS_EXPORT ainos_status_t ainos_model_cancel_download(const char* model_id);

/**
 * Pause an ongoing model download.
 * @param model_id The model identifier
 * @return AINOS_OK if download was paused
 */
AINOS_EXPORT ainos_status_t ainos_model_pause_download(const char* model_id);

/**
 * Resume a paused model download.
 * @param model_id The model identifier
 * @return AINOS_OK if download was resumed
 */
AINOS_EXPORT ainos_status_t ainos_model_resume_download(const char* model_id);

/**
 * Load a model into memory for inference.
 * @param model_id  The model identifier to load
 * @param callback  Completion callback (can be NULL)
 * @param user_data User data passed to callback
 * @return AINOS_OK if load was initiated
 */
AINOS_EXPORT ainos_status_t ainos_model_load(
    const char* model_id,
    ainos_model_load_callback_t callback,
    void* user_data
);

/**
 * Unload a model from memory.
 * @param model_id The model identifier to unload
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_unload(const char* model_id);

/**
 * Check if a model is currently loaded.
 * @param model_id The model identifier
 * @param loaded   Output parameter, true if loaded
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_is_loaded(const char* model_id, bool* loaded);

/**
 * Delete a downloaded model from cache.
 * @param model_id The model identifier
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_delete(const char* model_id);

/**
 * Get the cache size information.
 * @param used_mb  Output parameter for used cache in MB
 * @param total_mb Output parameter for total cache limit in MB
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_get_cache_size(float* used_mb, float* total_mb);

/**
 * Clear the model cache.
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_clear_cache(void);

/**
 * Get the current download progress for a model.
 * @param model_id The model identifier
 * @param progress Output progress information
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_get_download_progress(
    const char* model_id,
    ainos_model_download_progress_t* progress
);

/**
 * Free a model info list returned by ainos_model_get_available.
 * @param models The model info array to free
 * @param count  The number of entries
 */
AINOS_EXPORT void ainos_model_free_list(ainos_model_info_t* models, size_t count);

/**
 * Free a model info struct.
 * @param info The model info to free
 */
AINOS_EXPORT void ainos_model_free_info(ainos_model_info_t* info);

/**
 * Verify model integrity using SHA-256 checksum.
 * @param model_id The model identifier
 * @param valid    Output parameter, true if checksum matches
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_model_verify_checksum(const char* model_id, bool* valid);

/*============================================================================
 * Inference Engine
 *============================================================================*/

typedef enum {
    AINOS_INFERENCE_BACKEND_AUTO     = 0,
    AINOS_INFERENCE_BACKEND_CPU      = 1,
    AINOS_INFERENCE_BACKEND_GPU      = 2,
    AINOS_INFERENCE_BACKEND_NNAPI    = 3,
    AINOS_INFERENCE_BACKEND_COREML   = 4,
    AINOS_INFERENCE_BACKEND_ANE      = 5,
    AINOS_INFERENCE_BACKEND_DELEGATE = 6
} ainos_inference_backend_t;

typedef struct {
    ainos_inference_backend_t backend;
    uint32_t num_threads;
    bool     use_gpu;
    bool     use_npu;
    bool     allow_fp16;
    bool     enable_quantization;
    int      thermal_threshold;
    int      battery_threshold;
    uint32_t max_batch_size;
    uint32_t timeout_ms;
    char     delegate_options[512];
} ainos_inference_config_t;

typedef struct {
    int32_t* data;
    size_t   size;
    size_t   dimensions[4];
    int      num_dimensions;
    ainos_model_precision_t precision;
} ainos_tensor_t;

typedef struct {
    ainos_status_t      status;
    void*               output_data;
    size_t              output_size;
    float               inference_time_ms;
    float               preprocess_time_ms;
    float               postprocess_time_ms;
    float               total_time_ms;
    uint64_t            tokens_generated;
    uint64_t            tokens_per_second;
    ainos_thermal_status_t thermal_status;
    int                 battery_level;
    bool                 was_throttled;
    char                 error_message[256];
} ainos_inference_result_t;

typedef enum {
    AINOS_STREAM_EVENT_START          = 0,
    AINOS_STREAM_EVENT_TOKEN          = 1,
    AINOS_STREAM_EVENT_COMPLETE       = 2,
    AINOS_STREAM_EVENT_ERROR          = 3,
    AINOS_STREAM_EVENT_CANCELLED      = 4,
    AINOS_STREAM_EVENT_PROGRESS       = 5,
    AINOS_STREAM_EVENT_THERMAL_WARN   = 6
} ainos_stream_event_t;

typedef struct {
    ainos_stream_event_t event;
    uint32_t    sequence;
    const char* token_data;
    size_t      token_length;
    float       progress;
    ainos_status_t  error_code;
    char        error_message[256];
    ainos_thermal_status_t thermal_status;
    int         battery_level;
    float       inference_time_ms;
    uint64_t    tokens_so_far;
    bool        is_final;
} ainos_stream_event_data_t;

typedef void (*ainos_inference_callback_t)(ainos_status_t status, const ainos_inference_result_t* result, void* user_data);
typedef void (*ainos_stream_callback_t)(const ainos_stream_event_data_t* event, void* user_data);

/**
 * Get the default inference configuration.
 * @param config Output parameter for default config
 */
AINOS_EXPORT void ainos_inference_get_default_config(ainos_inference_config_t* config);

/**
 * Initialize the inference engine.
 * @param config Inference configuration
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_inference_init(const ainos_inference_config_t* config);

/**
 * Shutdown the inference engine and release all resources.
 */
AINOS_EXPORT void ainos_inference_shutdown(void);

/**
 * Run inference on a loaded model synchronously.
 * @param model_id  The model identifier
 * @param input     Input tensor
 * @param output    Output tensor (caller must free via ainos_inference_free_tensor)
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_inference_run(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_tensor_t** output
);

/**
 * Run inference asynchronously with a completion callback.
 * @param model_id  The model identifier
 * @param input     Input tensor (copied internally, caller can free)
 * @param callback  Completion callback
 * @param user_data User data passed to callback
 * @return AINOS_OK if inference was queued
 */
AINOS_EXPORT ainos_status_t ainos_inference_run_async(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_inference_callback_t callback,
    void* user_data
);

/**
 * Run inference with streaming output (for LLM/text generation).
 * @param model_id   The model identifier
 * @param input      Input tensor
 * @param stream_callback Callback for each stream event
 * @param completion_callback Callback when streaming completes
 * @param user_data  User data passed to callbacks
 * @return AINOS_OK if streaming was initiated
 */
AINOS_EXPORT ainos_status_t ainos_inference_run_stream(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_stream_callback_t stream_callback,
    ainos_inference_callback_t completion_callback,
    void* user_data
);

/**
 * Cancel a running inference operation.
 * @param model_id The model identifier
 * @return AINOS_OK if inference was cancelled
 */
AINOS_EXPORT ainos_status_t ainos_inference_cancel(const char* model_id);

/**
 * Cancel a streaming inference operation.
 * @param model_id The model identifier
 * @return AINOS_OK if stream was cancelled
 */
AINOS_EXPORT ainos_status_t ainos_inference_cancel_stream(const char* model_id);

/**
 * Check if a model is currently running inference.
 * @param model_id The model identifier
 * @param running  Output parameter, true if inference is running
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_inference_is_running(const char* model_id, bool* running);

/**
 * Get the current inference backend being used.
 * @return The backend type
 */
AINOS_EXPORT ainos_inference_backend_t ainos_inference_get_active_backend(void);

/**
 * Get the available backends on this device.
 * @param backends Output array of available backends (caller must free)
 * @param count    Output count
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_inference_get_available_backends(
    ainos_inference_backend_t** backends,
    size_t* count
);

/**
 * Free an inference result.
 * @param result The result to free
 */
AINOS_EXPORT void ainos_inference_free_result(ainos_inference_result_t* result);

/**
 * Free an inference tensor.
 * @param tensor The tensor to free
 */
AINOS_EXPORT void ainos_inference_free_tensor(ainos_tensor_t* tensor);

/*============================================================================
 * Streaming Handler
 *============================================================================*/

typedef uint64_t ainos_stream_id_t;

#define AINOS_STREAM_ID_INVALID 0

/**
 * Open a new inference stream.
 * @param model_id        The model identifier
 * @param stream_id       Output parameter for the stream ID
 * @param stream_callback Callback for stream events
 * @param user_data       User data
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_stream_open(
    const char* model_id,
    ainos_stream_id_t* stream_id,
    ainos_stream_callback_t stream_callback,
    void* user_data
);

/**
 * Send data to an open stream.
 * @param stream_id The stream ID
 * @param data      The data to send
 * @param size      Size of data in bytes
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_stream_send(
    ainos_stream_id_t stream_id,
    const void* data,
    size_t size
);

/**
 * Close an open stream.
 * @param stream_id The stream ID to close
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_stream_close(ainos_stream_id_t stream_id);

/**
 * Check if a stream is active.
 * @param stream_id The stream ID
 * @param active    Output parameter, true if stream is active
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_stream_is_active(ainos_stream_id_t stream_id, bool* active);

/*============================================================================
 * Daemon Communication (AinosOS IPC)
 *============================================================================*/

typedef enum {
    AINOS_DAEMON_CMD_HEARTBEAT        = 0x0001,
    AINOS_DAEMON_CMD_GET_STATUS       = 0x0002,
    AINOS_DAEMON_CMD_REGISTER_CLIENT  = 0x0003,
    AINOS_DAEMON_CMD_UNREGISTER_CLIENT= 0x0004,
    AINOS_DAEMON_CMD_MODEL_LIST       = 0x0010,
    AINOS_DAEMON_CMD_MODEL_DOWNLOAD   = 0x0011,
    AINOS_DAEMON_CMD_MODEL_DELETE     = 0x0012,
    AINOS_DAEMON_CMD_INFERENCE       = 0x0020,
    AINOS_DAEMON_CMD_INFERENCE_STREAM= 0x0021,
    AINOS_DAEMON_CMD_CANCEL          = 0x0022,
    AINOS_DAEMON_CMD_SYSTEM_UPDATE   = 0x0030,
    AINOS_DAEMON_CMD_GET_LOGS        = 0x0031,
    AINOS_DAEMON_CMD_RESTART         = 0x0032,
    AINOS_DAEMON_CMD_SHUTDOWN        = 0x0033,
    AINOS_DAEMON_CMD_PUSH_NOTIFICATION = 0x0040,
    AINOS_DAEMON_CMD_THERMAL_STATUS  = 0x0050,
    AINOS_DAEMON_CMD_BATTERY_STATUS  = 0x0051,
    AINOS_DAEMON_CMD_DEVICE_INFO     = 0x0060
} ainos_daemon_command_t;

typedef struct {
    uint16_t command;
    uint16_t flags;
    uint32_t sequence;
    uint64_t timestamp;
    uint32_t payload_size;
    uint8_t  payload[4096];
} ainos_daemon_message_t;

typedef struct {
    bool     connected;
    char     daemon_version[64];
    char     daemon_host[256];
    uint16_t daemon_port;
    uint32_t uptime_seconds;
    uint32_t active_clients;
    uint64_t messages_sent;
    uint64_t messages_received;
    uint64_t last_heartbeat;
    ainos_thermal_status_t thermal_status;
    int      battery_level;
    char     device_id[128];
    char     os_version[64];
} ainos_daemon_status_t;

typedef void (*ainos_daemon_message_callback_t)(const ainos_daemon_message_t* message, void* user_data);
typedef void (*ainos_daemon_connection_callback_t)(bool connected, void* user_data);

/**
 * Connect to the AinosOS daemon.
 * @param host       Daemon host address (e.g., "127.0.0.1")
 * @param port       Daemon port
 * @param timeout_ms Connection timeout in milliseconds
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_daemon_connect(
    const char* host,
    uint16_t port,
    uint32_t timeout_ms
);

/**
 * Disconnect from the AinosOS daemon.
 */
AINOS_EXPORT void ainos_daemon_disconnect(void);

/**
 * Check if connected to the daemon.
 * @return true if connected
 */
AINOS_EXPORT bool ainos_daemon_is_connected(void);

/**
 * Send a message to the daemon and wait for response.
 * @param command      The command to send
 * @param request      Request payload
 * @param request_size Size of request payload
 * @param response     Output response buffer
 * @param response_size Size of response buffer (in/out)
 * @param timeout_ms   Timeout in milliseconds
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_daemon_send_command(
    ainos_daemon_command_t command,
    const void* request,
    size_t request_size,
    void* response,
    size_t* response_size,
    uint32_t timeout_ms
);

/**
 * Send a message asynchronously to the daemon.
 * @param message  The message to send
 * @param callback Response callback (can be NULL)
 * @param user_data User data
 * @return AINOS_OK if message was sent
 */
AINOS_EXPORT ainos_status_t ainos_daemon_send_async(
    const ainos_daemon_message_t* message,
    ainos_daemon_message_callback_t callback,
    void* user_data
);

/**
 * Register a connection state callback.
 * @param callback Callback for connection state changes
 * @param user_data User data
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_daemon_register_connection_callback(
    ainos_daemon_connection_callback_t callback,
    void* user_data
);

/**
 * Get the current daemon status.
 * @param status Output daemon status
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_daemon_get_status(ainos_daemon_status_t* status);

/**
 * Send a heartbeat to the daemon.
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_daemon_send_heartbeat(void);

/*============================================================================
 * Background Services
 *============================================================================*/

typedef enum {
    AINOS_BACKGROUND_TASK_DOWNLOAD     = 0,
    AINOS_BACKGROUND_TASK_INFERENCE    = 1,
    AINOS_BACKGROUND_TASK_SYNC         = 2,
    AINOS_BACKGROUND_TASK_MAINTENANCE  = 3,
    AINOS_BACKGROUND_TASK_UPDATE_CHECK = 4
} ainos_background_task_type_t;

typedef struct {
    ainos_background_task_type_t type;
    char     task_id[64];
    char     task_name[128];
    uint32_t interval_minutes;
    uint32_t max_execution_time_seconds;
    bool     requires_network;
    bool     requires_charging;
    bool     requires_idle;
    uint32_t min_battery_level;
    uint32_t retry_count;
    uint32_t max_retries;
    char     description[256];
} ainos_background_task_config_t;

typedef void (*ainos_background_task_callback_t)(const char* task_id, ainos_status_t status, void* user_data);

/**
 * Register a background task.
 * @param config    Task configuration
 * @param callback  Task execution callback
 * @param user_data User data
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_background_register_task(
    const ainos_background_task_config_t* config,
    ainos_background_task_callback_t callback,
    void* user_data
);

/**
 * Unregister a background task.
 * @param task_id The task ID to unregister
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_background_unregister_task(const char* task_id);

/**
 * Start a registered background task immediately.
 * @param task_id The task ID
 * @return AINOS_OK if task was started
 */
AINOS_EXPORT ainos_status_t ainos_background_start_task(const char* task_id);

/**
 * Stop a running background task.
 * @param task_id The task ID
 * @return AINOS_OK if task was stopped
 */
AINOS_EXPORT ainos_status_t ainos_background_stop_task(const char* task_id);

/**
 * Get the status of a background task.
 * @param task_id The task ID
 * @param running Output parameter, true if task is running
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_background_task_status(const char* task_id, bool* running);

/*============================================================================
 * Push Notifications
 *============================================================================*/

typedef enum {
    AINOS_NOTIFICATION_PRIORITY_MIN    = 0,
    AINOS_NOTIFICATION_PRIORITY_LOW    = 1,
    AINOS_NOTIFICATION_PRIORITY_DEFAULT = 2,
    AINOS_NOTIFICATION_PRIORITY_HIGH   = 3,
    AINOS_NOTIFICATION_PRIORITY_MAX    = 4
} ainos_notification_priority_t;

typedef struct {
    char     notification_id[64];
    char     channel_id[64];
    char     channel_name[128];
    char     title[256];
    char     body[1024];
    char     ticker[256];
    ainos_notification_priority_t priority;
    uint32_t importance;
    bool     auto_cancel;
    bool     show_timestamp;
    bool     vibrate;
    bool     sound;
    bool     ongoing;
    bool     alert_once;
    int      timeout_after_ms;
    char     group_key[64];
    char     metadata_json[512];
    int64_t  scheduled_time_ms;
    bool     is_scheduled;
} ainos_notification_t;

typedef void (*ainos_notification_action_callback_t)(const char* notification_id, const char* action, void* user_data);

/**
 * Show a notification.
 * @param notification Notification data
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_show(const ainos_notification_t* notification);

/**
 * Cancel a notification.
 * @param notification_id The notification ID to cancel
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_cancel(const char* notification_id);

/**
 * Cancel all notifications.
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_cancel_all(void);

/**
 * Create a notification channel.
 * @param channel_id   Channel ID
 * @param channel_name Channel display name
 * @param importance   Importance level (1-5)
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_create_channel(
    const char* channel_id,
    const char* channel_name,
    int importance
);

/**
 * Delete a notification channel.
 * @param channel_id Channel ID to delete
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_delete_channel(const char* channel_id);

/**
 * Register a notification action callback.
 * @param callback  Callback for notification actions
 * @param user_data User data
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_register_action_callback(
    ainos_notification_action_callback_t callback,
    void* user_data
);

/**
 * Schedule a notification for future delivery.
 * @param notification Notification with scheduled_time_ms set
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_notification_schedule(const ainos_notification_t* notification);

/*============================================================================
 * Foreground Service
 *============================================================================*/

typedef struct {
    char     service_name[128];
    char     notification_title[256];
    char     notification_text[1024];
    int      notification_id;
    char     channel_id[64];
    bool     show_foreground_notification;
    bool     keep_alive;
    uint32_t keep_alive_interval_ms;
    bool     allow_while_in_use;
    bool     require_battery_not_low;
    uint32_t max_restart_count;
    uint32_t restart_delay_ms;
} ainos_foreground_service_config_t;

/**
 * Start the foreground service.
 * @param config Service configuration
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_foreground_service_start(
    const ainos_foreground_service_config_t* config
);

/**
 * Stop the foreground service.
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_foreground_service_stop(void);

/**
 * Update the foreground service notification.
 * @param title New notification title
 * @param text  New notification text
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_foreground_service_update_notification(
    const char* title,
    const char* text
);

/**
 * Check if the foreground service is running.
 * @param running Output parameter, true if running
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_foreground_service_is_running(bool* running);

/*============================================================================
 * Device Information
 *============================================================================*/

typedef struct {
    char     device_model[128];
    char     device_manufacturer[128];
    char     os_version[64];
    char     os_build[64];
    char     architecture[16];
    uint32_t cpu_cores;
    uint32_t cpu_max_freq_mhz;
    uint32_t cpu_min_freq_mhz;
    uint64_t total_ram_mb;
    uint64_t available_ram_mb;
    uint64_t total_storage_mb;
    uint64_t available_storage_mb;
    bool     is_emulator;
    bool     has_npu;
    bool     has_gpu;
    bool     has_neural_engine;
    char     gpu_info[128];
    char     npu_info[128];
    uint32_t screen_width_px;
    uint32_t screen_height_px;
    float    screen_density;
    float    screen_refresh_rate;
    char     android_api_level[16];
    char     ios_platform[16];
    bool     is_64bit;
    bool     supports_fp16;
    bool     supports_int8;
    uint32_t battery_capacity_mah;
} ainos_device_info_t;

/**
 * Get device information.
 * @param info Output device information
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_device_get_info(ainos_device_info_t* info);

/**
 * Check if the device meets minimum requirements for AI inference.
 * @param meets_minimum Output parameter
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_device_check_minimum_requirements(bool* meets_minimum);

/**
 * Get the Android API level (Android only).
 * @param api_level Output API level
 * @return AINOS_OK on success, AINOS_ERROR_NOT_SUPPORTED on iOS
 */
AINOS_EXPORT ainos_status_t ainos_device_get_api_level(int* api_level);

/*============================================================================
 * Utility Functions
 *============================================================================*/

/**
 * Convert a status code to a human-readable string.
 * @param status The status code
 * @return Static string describing the status
 */
AINOS_EXPORT const char* ainos_status_to_string(ainos_status_t status);

/**
 * Convert a thermal status to a human-readable string.
 * @param status The thermal status
 * @return Static string describing the status
 */
AINOS_EXPORT const char* ainos_thermal_status_to_string(ainos_thermal_status_t status);

/**
 * Convert a battery status to a human-readable string.
 * @param status The battery status
 * @return Static string describing the status
 */
AINOS_EXPORT const char* ainos_battery_status_to_string(ainos_battery_status_t status);

/**
 * Sleep for the specified number of milliseconds.
 * @param ms Milliseconds to sleep
 */
AINOS_EXPORT void ainos_sleep(uint32_t ms);

/**
 * Get the current time in milliseconds since epoch.
 * @return Current timestamp in milliseconds
 */
AINOS_EXPORT int64_t ainos_get_timestamp_ms(void);

/**
 * Generate a UUID v4 string.
 * @param buffer Output buffer (must be at least 37 bytes)
 * @param buffer_size Size of output buffer
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_generate_uuid(char* buffer, size_t buffer_size);

/**
 * Create a directory recursively.
 * @param path Directory path to create
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_mkdir_p(const char* path);

/**
 * Check if a file exists.
 * @param path File path to check
 * @return true if file exists
 */
AINOS_EXPORT bool ainos_file_exists(const char* path);

/**
 * Get file size.
 * @param path File path
 * @param size Output file size
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_file_size(const char* path, uint64_t* size);

/**
 * Delete a file.
 * @param path File path to delete
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_file_delete(const char* path);

/**
 * Get the application cache directory.
 * @param buffer Output buffer for path
 * @param buffer_size Size of output buffer
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_get_cache_dir(char* buffer, size_t buffer_size);

/**
 * Get the application data directory.
 * @param buffer Output buffer for path
 * @param buffer_size Size of output buffer
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_get_data_dir(char* buffer, size_t buffer_size);

/**
 * Format a byte size into a human-readable string.
 * @param bytes  Size in bytes
 * @param buffer Output buffer
 * @param buffer_size Size of output buffer
 * @return Pointer to buffer
 */
AINOS_EXPORT const char* ainos_format_bytes(uint64_t bytes, char* buffer, size_t buffer_size);

/**
 * Calculate SHA-256 hash of a file.
 * @param path     File path
 * @param hash_hex Output buffer for hex hash (must be at least 65 bytes)
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_sha256_file(const char* path, char* hash_hex);

/**
 * Base64 encode data.
 * @param input      Input data
 * @param input_size Input size
 * @param output     Output buffer
 * @param output_size On input, buffer size; on output, encoded size
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_base64_encode(
    const uint8_t* input,
    size_t input_size,
    char* output,
    size_t* output_size
);

/**
 * Base64 decode data.
 * @param input      Input string
 * @param output     Output buffer
 * @param output_size On input, buffer size; on output, decoded size
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_base64_decode(
    const char* input,
    uint8_t* output,
    size_t* output_size
);

/**
 * Compress data using zlib (deflate).
 * @param input        Input data
 * @param input_size   Input size
 * @param output       Output buffer (caller must free)
 * @param output_size  Output compressed size
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_compress(
    const uint8_t* input,
    size_t input_size,
    uint8_t** output,
    size_t* output_size
);

/**
 * Decompress data using zlib (inflate).
 * @param input        Input compressed data
 * @param input_size   Input size
 * @param output       Output buffer (caller must free)
 * @param output_size  Output decompressed size
 * @param max_output_size Maximum allowed output size
 * @return AINOS_OK on success
 */
AINOS_EXPORT ainos_status_t ainos_decompress(
    const uint8_t* input,
    size_t input_size,
    uint8_t** output,
    size_t* output_size,
    size_t max_output_size
);

#ifdef __cplusplus
}
#endif

#endif /* AINOS_PLATFORM_MOBILE_H */