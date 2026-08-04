/**
 * ainos_mobile_common.c
 * Common shared implementation for Ainos mobile platform
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos_mobile_common.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#ifdef _WIN32
#include <windows.h>
#include <direct.h>
#include <io.h>
#else
#include <unistd.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <pthread.h>
#endif

/*============================================================================
 * Global State
 *============================================================================*/

ainos_log_callback_t g_ainos_log_callback = NULL;
ainos_platform_state_t g_ainos_state;

/*============================================================================
 * Initialization Check
 *============================================================================*/

bool ainos_platform_check_initialized(void)
{
    if (!g_ainos_state.initialized) {
        AINOS_LOG_E("Common", "Platform not initialized. Call ainos_platform_init() first.");
        return false;
    }
    return true;
}

/*============================================================================
 * Platform Detection
 *============================================================================*/

ainos_platform_type_t ainos_platform_detect(void)
{
#if defined(__ANDROID__)
    return AINOS_PLATFORM_ANDROID;
#elif defined(__APPLE__)
    #include <TargetConditionals.h>
    #if TARGET_OS_IPHONE
        return AINOS_PLATFORM_IOS;
    #else
        return AINOS_PLATFORM_UNKNOWN;
    #endif
#else
    return AINOS_PLATFORM_UNKNOWN;
#endif
}

/*============================================================================
 * Initialization
 *============================================================================*/

ainos_status_t ainos_platform_init(
    const char* app_name,
    const char* app_version,
    ainos_log_callback_t log_callback)
{
    if (g_ainos_state.initialized) {
        return AINOS_ERROR_ALREADY_INITIALIZED;
    }

    if (!app_name || !app_version) {
        return AINOS_ERROR_INVALID_PARAM;
    }

    memset(&g_ainos_state, 0, sizeof(g_ainos_state));

    g_ainos_log_callback = log_callback;

    strncpy(g_ainos_state.app_name, app_name, sizeof(g_ainos_state.app_name) - 1);
    strncpy(g_ainos_state.app_version, app_version, sizeof(g_ainos_state.app_version) - 1);

    g_ainos_state.platform_type = ainos_platform_detect();
    g_ainos_state.thermal_status = AINOS_THERMAL_STATUS_NORMAL;
    g_ainos_state.battery_status = AINOS_BATTERY_STATUS_UNKNOWN;
    g_ainos_state.battery_level = 100;
    g_ainos_state.power_mode = AINOS_POWER_MODE_NORMAL;
    g_ainos_state.daemon_connected = false;
    g_ainos_state.message_sequence = 0;
    g_ainos_state.foreground_service_running = false;
    g_ainos_state.foreground_notification_id = 1001;

    AINOS_LOG_I("Common", "Ainos Platform v%s initializing for %s",
                AINOS_PLATFORM_MOBILE_VERSION,
                g_ainos_state.platform_type == AINOS_PLATFORM_ANDROID ? "Android" :
                g_ainos_state.platform_type == AINOS_PLATFORM_IOS ? "iOS" : "Unknown");

    ainos_status_t status = ainos_platform_impl_init();
    if (status != AINOS_OK) {
        AINOS_LOG_E("Common", "Platform-specific init failed: %d", status);
        memset(&g_ainos_state, 0, sizeof(g_ainos_state));
        return status;
    }

    g_ainos_state.initialized = true;
    AINOS_LOG_I("Common", "Ainos Platform initialized successfully");
    return AINOS_OK;
}

void ainos_platform_shutdown(void)
{
    if (!g_ainos_state.initialized) {
        return;
    }

    AINOS_LOG_I("Common", "Ainos Platform shutting down");

    // Unregister callbacks
    if (g_ainos_state.thermal_callback) {
        ainos_thermal_unregister_callback();
    }
    if (g_ainos_state.battery_callback) {
        ainos_battery_unregister_callback();
    }

    // Disconnect from daemon
    if (g_ainos_state.daemon_connected) {
        ainos_daemon_disconnect();
    }

    // Stop foreground service
    if (g_ainos_state.foreground_service_running) {
        ainos_foreground_service_stop();
    }

    // Shutdown inference
    ainos_inference_shutdown();

    // Platform-specific shutdown
    ainos_platform_impl_shutdown();

    memset(&g_ainos_state, 0, sizeof(g_ainos_state));
    g_ainos_log_callback = NULL;
    AINOS_LOG_I("Common", "Ainos Platform shutdown complete");
}

bool ainos_platform_is_initialized(void)
{
    return g_ainos_state.initialized;
}

const char* ainos_platform_version(void)
{
    return AINOS_PLATFORM_MOBILE_VERSION;
}

/*============================================================================
 * Thermal Management
 *============================================================================*/

ainos_thermal_status_t ainos_thermal_get_status(void)
{
    if (!ainos_platform_check_initialized()) {
        return AINOS_THERMAL_STATUS_UNKNOWN;
    }
    ainos_thermal_status_t status;
    if (ainos_platform_impl_thermal_get_status(&status) == AINOS_OK) {
        g_ainos_state.thermal_status = status;
    }
    return g_ainos_state.thermal_status;
}

ainos_thermal_throttle_t ainos_thermal_get_throttle_level(void)
{
    ainos_thermal_status_t status = ainos_thermal_get_status();
    switch (status) {
        case AINOS_THERMAL_STATUS_NORMAL:
            return AINOS_THERMAL_THROTTLE_NONE;
        case AINOS_THERMAL_STATUS_WARM:
            return AINOS_THERMAL_THROTTLE_MILD;
        case AINOS_THERMAL_STATUS_HOT:
            return AINOS_THERMAL_THROTTLE_MODERATE;
        case AINOS_THERMAL_STATUS_CRITICAL:
            return AINOS_THERMAL_THROTTLE_SEVERE;
        case AINOS_THERMAL_STATUS_EMERGENCY:
            return AINOS_THERMAL_THROTTLE_SHUTDOWN;
        default:
            return AINOS_THERMAL_THROTTLE_NONE;
    }
}

ainos_status_t ainos_thermal_get_cpu_temperature(float* temperature)
{
    if (!temperature) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;
    return ainos_platform_impl_thermal_get_cpu_temperature(temperature);
}

ainos_status_t ainos_thermal_get_battery_temperature(float* temperature)
{
    if (!temperature) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;
    return ainos_platform_impl_thermal_get_battery_temperature(temperature);
}

ainos_status_t ainos_thermal_register_callback(
    void (*callback)(ainos_thermal_status_t, ainos_thermal_status_t, void*),
    void* user_data)
{
    if (!callback) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    g_ainos_state.thermal_callback = callback;
    g_ainos_state.thermal_callback_userdata = user_data;
    return AINOS_OK;
}

void ainos_thermal_unregister_callback(void)
{
    g_ainos_state.thermal_callback = NULL;
    g_ainos_state.thermal_callback_userdata = NULL;
}

int ainos_thermal_get_recommended_batch_size(void)
{
    ainos_thermal_status_t status = ainos_thermal_get_status();
    switch (status) {
        case AINOS_THERMAL_STATUS_NORMAL:
            return 8;
        case AINOS_THERMAL_STATUS_WARM:
            return 4;
        case AINOS_THERMAL_STATUS_HOT:
            return 2;
        case AINOS_THERMAL_STATUS_CRITICAL:
        case AINOS_THERMAL_STATUS_EMERGENCY:
            return 1;
        default:
            return 4;
    }
}

bool ainos_thermal_should_throttle_inference(void)
{
    ainos_thermal_status_t status = ainos_thermal_get_status();
    return status >= AINOS_THERMAL_STATUS_HOT;
}

/*============================================================================
 * Battery Management
 *============================================================================*/

ainos_status_t ainos_battery_get_level(int* level)
{
    if (!level) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_status_t status = ainos_platform_impl_battery_get_level(&g_ainos_state.battery_level);
    *level = g_ainos_state.battery_level;
    return status;
}

ainos_battery_status_t ainos_battery_get_status(void)
{
    if (!ainos_platform_check_initialized()) {
        return AINOS_BATTERY_STATUS_UNKNOWN;
    }
    ainos_platform_impl_battery_get_status(&g_ainos_state.battery_status);
    return g_ainos_state.battery_status;
}

ainos_power_mode_t ainos_battery_get_power_mode(void)
{
    return g_ainos_state.power_mode;
}

bool ainos_battery_is_low_power_mode(void)
{
    return g_ainos_state.power_mode == AINOS_POWER_MODE_LOW_POWER ||
           g_ainos_state.power_mode == AINOS_POWER_MODE_ULTRA_SAVING;
}

bool ainos_battery_is_charging(void)
{
    ainos_battery_status_t status = ainos_battery_get_status();
    return status == AINOS_BATTERY_STATUS_CHARGING || status == AINOS_BATTERY_STATUS_FULL;
}

ainos_status_t ainos_battery_get_estimated_time(int* minutes)
{
    if (!minutes) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    int level;
    ainos_status_t status = ainos_battery_get_level(&level);
    if (status != AINOS_OK) return status;

    if (ainos_battery_is_charging()) {
        // Estimate time to full: roughly 1.5 minutes per percent for fast charge
        *minutes = (100 - level) * 90 / 100;
        if (*minutes < 1) *minutes = 1;
    } else {
        // Estimate time remaining: roughly 2 minutes per percent
        *minutes = level * 2;
        if (*minutes < 0) *minutes = 0;
    }
    return AINOS_OK;
}

ainos_status_t ainos_battery_register_callback(
    void (*callback)(ainos_battery_status_t, int, void*),
    void* user_data)
{
    if (!callback) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    g_ainos_state.battery_callback = callback;
    g_ainos_state.battery_callback_userdata = user_data;
    return AINOS_OK;
}

void ainos_battery_unregister_callback(void)
{
    g_ainos_state.battery_callback = NULL;
    g_ainos_state.battery_callback_userdata = NULL;
}

ainos_status_t ainos_battery_request_power_mode(ainos_power_mode_t mode)
{
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    if (mode < AINOS_POWER_MODE_NORMAL || mode > AINOS_POWER_MODE_PERFORMANCE) {
        return AINOS_ERROR_INVALID_PARAM;
    }

    g_ainos_state.power_mode = mode;
    AINOS_LOG_I("Battery", "Power mode set to %d", mode);
    return AINOS_OK;
}

/*============================================================================
 * Permission Management
 *============================================================================*/

static const char* PERMISSION_NAMES[] = {
    "Camera",
    "Microphone",
    "Storage",
    "Notifications",
    "Background Service",
    "Network State",
    "Bluetooth",
    "Location",
    "Vibrate",
    "Wake Lock",
    "Foreground Service",
    "Schedule Exact Alarm",
    "Post Notifications"
};

ainos_status_t ainos_permission_check(
    ainos_permission_t permission,
    ainos_permission_state_t* state)
{
    if (!state) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;
    if (permission < 0 || permission >= AINOS_PERMISSION_COUNT) {
        return AINOS_ERROR_INVALID_PARAM;
    }

    // Platform-specific permission check
    // Default implementation returns granted for non-sensitive permissions
    *state = AINOS_PERMISSION_STATE_GRANTED;
    return AINOS_OK;
}

ainos_status_t ainos_permission_request(
    ainos_permission_t permission,
    ainos_permission_callback_t callback,
    void* user_data)
{
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;
    if (permission < 0 || permission >= AINOS_PERMISSION_COUNT) {
        return AINOS_ERROR_INVALID_PARAM;
    }

    AINOS_LOG_I("Permissions", "Requesting permission: %s", PERMISSION_NAMES[permission]);

    // Platform-specific implementation handles the UI prompt
    if (callback) {
        callback(permission, AINOS_PERMISSION_STATE_GRANTED, user_data);
    }
    return AINOS_OK;
}

ainos_status_t ainos_permission_request_multiple(
    const ainos_permission_t* permissions,
    size_t count,
    ainos_permission_callback_t callback,
    void* user_data)
{
    if (!permissions || count == 0) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    for (size_t i = 0; i < count; i++) {
        if (permissions[i] < 0 || permissions[i] >= AINOS_PERMISSION_COUNT) {
            return AINOS_ERROR_INVALID_PARAM;
        }
    }

    AINOS_LOG_I("Permissions", "Requesting %zu permissions", count);

    for (size_t i = 0; i < count; i++) {
        if (callback) {
            callback(permissions[i], AINOS_PERMISSION_STATE_GRANTED, user_data);
        }
    }
    return AINOS_OK;
}

ainos_status_t ainos_permission_open_settings(void)
{
    AINOS_LOG_I("Permissions", "Opening app settings");
    // Platform-specific implementation
    return AINOS_OK;
}

bool ainos_permission_should_show_rationale(ainos_permission_t permission)
{
    (void)permission;
    return false;
}

const char* ainos_permission_get_name(ainos_permission_t permission)
{
    if (permission >= 0 && permission < AINOS_PERMISSION_COUNT) {
        return PERMISSION_NAMES[permission];
    }
    return "Unknown";
}

/*============================================================================
 * Model Management
 *============================================================================*/

// Internal model registry
#define MAX_MODELS 64

typedef struct {
    ainos_model_info_t info;
    ainos_model_download_callback_t download_callback;
    void* download_callback_userdata;
    bool downloading;
    bool loaded;
} ainos_model_entry_t;

static ainos_model_entry_t g_model_registry[MAX_MODELS];
static int g_model_count = 0;

static ainos_model_entry_t* find_model_entry(const char* model_id)
{
    for (int i = 0; i < g_model_count; i++) {
        if (strcmp(g_model_registry[i].info.model_id, model_id) == 0) {
            return &g_model_registry[i];
        }
    }
    return NULL;
}

static void add_default_models(void)
{
    // LLM Models
    const char* model_ids[] = {
        "ainos-llm-7b-q4", "ainos-llm-3b-fp16", "ainos-llm-1b-int8",
        "ainos-vision-base", "ainos-vision-small",
        "ainos-embedding-base", "ainos-embedding-small",
        "ainos-audio-base"
    };
    const char* model_names[] = {
        "Ainos LLM 7B Q4", "Ainos LLM 3B FP16", "Ainos LLM 1B INT8",
        "Ainos Vision Base", "Ainos Vision Small",
        "Ainos Embedding Base", "Ainos Embedding Small",
        "Ainos Audio Base"
    };
    ainos_model_type_t types[] = {
        AINOS_MODEL_TYPE_LLM, AINOS_MODEL_TYPE_LLM, AINOS_MODEL_TYPE_LLM,
        AINOS_MODEL_TYPE_VISION, AINOS_MODEL_TYPE_VISION,
        AINOS_MODEL_TYPE_EMBEDDING, AINOS_MODEL_TYPE_EMBEDDING,
        AINOS_MODEL_TYPE_AUDIO
    };
    ainos_model_format_t formats[] = {
        AINOS_MODEL_FORMAT_TFLITE, AINOS_MODEL_FORMAT_TFLITE, AINOS_MODEL_FORMAT_TFLITE,
        AINOS_MODEL_FORMAT_COREML, AINOS_MODEL_FORMAT_TFLITE,
        AINOS_MODEL_FORMAT_TFLITE, AINOS_MODEL_FORMAT_ONNX,
        AINOS_MODEL_FORMAT_TFLITE
    };
    ainos_model_precision_t precisions[] = {
        AINOS_MODEL_PRECISION_INT4, AINOS_MODEL_PRECISION_FP16, AINOS_MODEL_PRECISION_INT8,
        AINOS_MODEL_PRECISION_FP16, AINOS_MODEL_PRECISION_INT8,
        AINOS_MODEL_PRECISION_FP16, AINOS_MODEL_PRECISION_FP32,
        AINOS_MODEL_PRECISION_FP16
    };
    float sizes_mb[] = {
        4096.0f, 2048.0f, 512.0f,
        1024.0f, 256.0f,
        128.0f, 32.0f,
        512.0f
    };
    float ram_mb[] = {
        4096.0f, 3072.0f, 1024.0f,
        2048.0f, 512.0f,
        256.0f, 64.0f,
        1024.0f
    };
    uint32_t param_counts[] = {
        7000000000, 3000000000, 1000000000,
        500000000, 100000000,
        50000000, 10000000,
        200000000
    };
    bool bundled[] = {
        false, false, true,
        false, true,
        true, true,
        false
    };

    g_model_count = sizeof(model_ids) / sizeof(model_ids[0]);

    for (int i = 0; i < g_model_count; i++) {
        ainos_model_entry_t* entry = &g_model_registry[i];
        memset(entry, 0, sizeof(*entry));
        strncpy(entry->info.model_id, model_ids[i], sizeof(entry->info.model_id) - 1);
        strncpy(entry->info.model_name, model_names[i], sizeof(entry->info.model_name) - 1);
        strncpy(entry->info.model_version, "1.0.0", sizeof(entry->info.model_version) - 1);
        entry->info.format = formats[i];
        entry->info.type = types[i];
        entry->info.precision = precisions[i];
        entry->info.state = AINOS_MODEL_STATE_NOT_DOWNLOADED;
        entry->info.file_size = (uint64_t)(sizes_mb[i] * 1024.0f * 1024.0f);
        entry->info.download_size = entry->info.file_size;
        entry->info.parameter_count = param_counts[i];
        entry->info.model_size_mb = sizes_mb[i];
        entry->info.required_ram_mb = ram_mb[i];
        entry->info.required_storage_mb = sizes_mb[i] * 1.2f;
        entry->info.is_bundled = bundled[i];
        entry->info.requires_network = true;
        entry->info.is_encrypted = false;
        snprintf(entry->info.download_url, sizeof(entry->info.download_url),
                 "https://models.ainos.ai/v1/%s", model_ids[i]);
        entry->info.last_used_timestamp = 0;
        entry->info.download_timestamp = 0;
        entry->downloading = false;
        entry->loaded = false;

        if (bundled[i]) {
            entry->info.state = AINOS_MODEL_STATE_DOWNLOADED;
        }
    }
}

ainos_status_t ainos_model_init(const char* cache_dir, uint32_t max_cache_size_mb)
{
    if (!cache_dir) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    strncpy(g_ainos_state.model_cache_dir, cache_dir, sizeof(g_ainos_state.model_cache_dir) - 1);
    g_ainos_state.max_cache_size_mb = max_cache_size_mb;

    // Ensure cache directory exists
    ainos_mkdir_p(cache_dir);

    // Clear model registry
    memset(g_model_registry, 0, sizeof(g_model_registry));
    g_model_count = 0;

    // Add default models
    add_default_models();

    AINOS_LOG_I("Models", "Model system initialized with cache at %s (max %u MB)",
                cache_dir, max_cache_size_mb);
    return AINOS_OK;
}

ainos_status_t ainos_model_get_available(ainos_model_info_t** models, size_t* count)
{
    if (!models || !count) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    *count = g_model_count;
    *models = (ainos_model_info_t*)malloc(sizeof(ainos_model_info_t) * g_model_count);
    if (!*models) return AINOS_ERROR_OUT_OF_MEMORY;

    for (int i = 0; i < g_model_count; i++) {
        memcpy(&(*models)[i], &g_model_registry[i].info, sizeof(ainos_model_info_t));
    }
    return AINOS_OK;
}

ainos_status_t ainos_model_get_info(const char* model_id, ainos_model_info_t* info)
{
    if (!model_id || !info) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    memcpy(info, &entry->info, sizeof(ainos_model_info_t));
    return AINOS_OK;
}

ainos_status_t ainos_model_download(
    const char* model_id,
    ainos_model_download_callback_t callback,
    void* user_data)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    if (entry->info.state == AINOS_MODEL_STATE_DOWNLOADED) {
        return AINOS_OK;
    }

    if (entry->downloading) {
        return AINOS_ERROR_BUSY;
    }

    entry->downloading = true;
    entry->download_callback = callback;
    entry->download_callback_userdata = user_data;
    entry->info.state = AINOS_MODEL_STATE_DOWNLOADING;
    entry->info.download_progress = 0;

    // Build cache path
    snprintf(entry->info.cache_path, sizeof(entry->info.cache_path),
             "%s/%s", g_ainos_state.model_cache_dir, model_id);
    snprintf(entry->info.model_path, sizeof(entry->info.model_path),
             "%s/%s/model.bin", g_ainos_state.model_cache_dir, model_id);

    AINOS_LOG_I("Models", "Starting download for model: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_cancel_download(const char* model_id)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    if (!entry->downloading) {
        return AINOS_OK;
    }

    entry->downloading = false;
    entry->info.state = AINOS_MODEL_STATE_NOT_DOWNLOADED;
    entry->info.download_progress = 0;
    AINOS_LOG_I("Models", "Download cancelled for model: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_pause_download(const char* model_id)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;
    if (!entry->downloading) return AINOS_ERROR_GENERAL;

    // Mark as paused by keeping state as downloading but store progress
    AINOS_LOG_I("Models", "Download paused for model: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_resume_download(const char* model_id)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    AINOS_LOG_I("Models", "Download resumed for model: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_load(
    const char* model_id,
    ainos_model_load_callback_t callback,
    void* user_data)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    if (entry->info.state != AINOS_MODEL_STATE_DOWNLOADED) {
        return AINOS_ERROR_MODEL_NOT_FOUND;
    }

    entry->info.state = AINOS_MODEL_STATE_LOADING;
    entry->loaded = true;
    entry->info.state = AINOS_MODEL_STATE_LOADED;
    entry->info.last_used_timestamp = ainos_get_timestamp_ms();

    AINOS_LOG_I("Models", "Model loaded: %s", model_id);

    if (callback) {
        callback(model_id, AINOS_OK, user_data);
    }
    return AINOS_OK;
}

ainos_status_t ainos_model_unload(const char* model_id)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    entry->loaded = false;
    entry->info.state = AINOS_MODEL_STATE_DOWNLOADED;
    AINOS_LOG_I("Models", "Model unloaded: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_is_loaded(const char* model_id, bool* loaded)
{
    if (!model_id || !loaded) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    *loaded = entry->loaded;
    return AINOS_OK;
}

ainos_status_t ainos_model_delete(const char* model_id)
{
    if (!model_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    entry->info.state = AINOS_MODEL_STATE_NOT_DOWNLOADED;
    entry->info.download_progress = 0;
    entry->loaded = false;
    entry->downloading = false;

    // Delete model files
    if (strlen(entry->info.model_path) > 0) {
        ainos_file_delete(entry->info.model_path);
    }

    AINOS_LOG_I("Models", "Model deleted: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_model_get_cache_size(float* used_mb, float* total_mb)
{
    if (!used_mb || !total_mb) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    *total_mb = (float)g_ainos_state.max_cache_size_mb;
    *used_mb = 0.0f;

    for (int i = 0; i < g_model_count; i++) {
        if (g_model_registry[i].info.state == AINOS_MODEL_STATE_DOWNLOADED ||
            g_model_registry[i].info.state == AINOS_MODEL_STATE_LOADED) {
            *used_mb += g_model_registry[i].info.model_size_mb;
        }
    }
    return AINOS_OK;
}

ainos_status_t ainos_model_clear_cache(void)
{
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    for (int i = 0; i < g_model_count; i++) {
        if (g_model_registry[i].info.state == AINOS_MODEL_STATE_DOWNLOADED ||
            g_model_registry[i].info.state == AINOS_MODEL_STATE_LOADED) {
            ainos_model_delete(g_model_registry[i].info.model_id);
        }
    }
    AINOS_LOG_I("Models", "Cache cleared");
    return AINOS_OK;
}

ainos_status_t ainos_model_get_download_progress(
    const char* model_id,
    ainos_model_download_progress_t* progress)
{
    if (!model_id || !progress) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    strncpy(progress->model_id, model_id, sizeof(progress->model_id) - 1);
    progress->state = entry->info.state;
    progress->progress = entry->info.download_progress;
    progress->total = entry->info.download_size;
    progress->speed_mbps = 0.0f;
    progress->estimated_seconds_remaining = 0;
    progress->error_message[0] = '\0';
    return AINOS_OK;
}

void ainos_model_free_list(ainos_model_info_t* models, size_t count)
{
    (void)count;
    if (models) {
        free(models);
    }
}

void ainos_model_free_info(ainos_model_info_t* info)
{
    (void)info;
    // Currently no dynamic allocations in info
}

ainos_status_t ainos_model_verify_checksum(const char* model_id, bool* valid)
{
    if (!model_id || !valid) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    // Check if file exists and has a checksum
    if (strlen(entry->info.checksum_sha256) == 0) {
        *valid = true; // No checksum to verify
        return AINOS_OK;
    }

    // Platform-specific checksum verification
    *valid = true;
    return AINOS_OK;
}

/*============================================================================
 * Inference Engine
 *============================================================================*/

void ainos_inference_get_default_config(ainos_inference_config_t* config)
{
    if (!config) return;
    memset(config, 0, sizeof(*config));
    config->backend = AINOS_INFERENCE_BACKEND_AUTO;
    config->num_threads = 4;
    config->use_gpu = true;
    config->use_npu = false;
    config->allow_fp16 = true;
    config->enable_quantization = true;
    config->thermal_threshold = 2; // HOT
    config->battery_threshold = 15;
    config->max_batch_size = 1;
    config->timeout_ms = 30000;
    config->delegate_options[0] = '\0';
}

ainos_status_t ainos_inference_init(const ainos_inference_config_t* config)
{
    (void)config;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;
    AINOS_LOG_I("Inference", "Inference engine initialized");
    return AINOS_OK;
}

void ainos_inference_shutdown(void)
{
    if (!g_ainos_state.initialized) return;
    AINOS_LOG_I("Inference", "Inference engine shutdown");
}

ainos_status_t ainos_inference_run(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_tensor_t** output)
{
    if (!model_id || !input || !output) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;
    if (!entry->loaded) return AINOS_ERROR_MODEL_LOAD_FAILED;

    // Check thermal conditions
    if (ainos_thermal_should_throttle_inference()) {
        AINOS_LOG_W("Inference", "Inference throttled due to thermal conditions");
        return AINOS_ERROR_THERMAL_THROTTLED;
    }

    // Check battery
    int battery_level;
    ainos_battery_get_level(&battery_level);
    if (battery_level < 10 && !ainos_battery_is_charging()) {
        AINOS_LOG_W("Inference", "Inference blocked due to low battery");
        return AINOS_ERROR_BATTERY_LOW;
    }

    // Allocate output tensor
    *output = (ainos_tensor_t*)calloc(1, sizeof(ainos_tensor_t));
    if (!*output) return AINOS_ERROR_OUT_OF_MEMORY;

    // Simulate inference (platform-specific implementation would do actual inference)
    (*output)->size = 1024;
    (*output)->data = (int32_t*)calloc((*output)->size, sizeof(int32_t));
    if (!(*output)->data) {
        free(*output);
        *output = NULL;
        return AINOS_ERROR_OUT_OF_MEMORY;
    }
    (*output)->num_dimensions = 1;
    (*output)->dimensions[0] = (*output)->size;
    (*output)->precision = AINOS_MODEL_PRECISION_FP32;

    entry->info.last_used_timestamp = ainos_get_timestamp_ms();
    AINOS_LOG_D("Inference", "Inference completed for model: %s", model_id);
    return AINOS_OK;
}

ainos_status_t ainos_inference_run_async(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_inference_callback_t callback,
    void* user_data)
{
    if (!model_id || !input) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    // For now, run synchronously and call callback
    ainos_tensor_t* output = NULL;
    ainos_status_t status = ainos_inference_run(model_id, input, &output);

    if (callback) {
        ainos_inference_result_t result;
        memset(&result, 0, sizeof(result));
        result.status = status;
        result.inference_time_ms = 100.0f;
        result.total_time_ms = 120.0f;
        result.thermal_status = g_ainos_state.thermal_status;
        result.battery_level = g_ainos_state.battery_level;
        result.was_throttled = (status == AINOS_ERROR_THERMAL_THROTTLED);
        result.output_data = output ? output->data : NULL;
        result.output_size = output ? output->size : 0;
        callback(status, &result, user_data);
    }

    if (output) {
        ainos_inference_free_tensor(output);
    }
    return AINOS_OK;
}

ainos_status_t ainos_inference_run_stream(
    const char* model_id,
    const ainos_tensor_t* input,
    ainos_stream_callback_t stream_callback,
    ainos_inference_callback_t completion_callback,
    void* user_data)
{
    if (!model_id || !input || !stream_callback) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    AINOS_LOG_I("Inference", "Starting streaming inference for model: %s", model_id);

    // Send start event
    ainos_stream_event_data_t start_event;
    memset(&start_event, 0, sizeof(start_event));
    start_event.event = AINOS_STREAM_EVENT_START;
    start_event.sequence = 0;
    start_event.progress = 0.0f;
    start_event.thermal_status = ainos_thermal_get_status();
    start_event.battery_level = g_ainos_state.battery_level;
    stream_callback(&start_event, user_data);

    // Simulate streaming tokens
    const char* sample_tokens[] = {
        "Hello", " I", " am", " Ainos", ",", " your", " AI", " assistant",
        ".", " How", " can", " I", " help", " you", " today", "?"
    };
    int num_tokens = sizeof(sample_tokens) / sizeof(sample_tokens[0]);

    for (int i = 0; i < num_tokens; i++) {
        // Check thermal conditions during streaming
        if (ainos_thermal_should_throttle_inference()) {
            ainos_stream_event_data_t thermal_event;
            memset(&thermal_event, 0, sizeof(thermal_event));
            thermal_event.event = AINOS_STREAM_EVENT_THERMAL_WARN;
            thermal_event.sequence = i + 1;
            thermal_event.thermal_status = ainos_thermal_get_status();
            stream_callback(&thermal_event, user_data);
        }

        ainos_stream_event_data_t token_event;
        memset(&token_event, 0, sizeof(token_event));
        token_event.event = AINOS_STREAM_EVENT_TOKEN;
        token_event.sequence = i + 1;
        token_event.token_data = sample_tokens[i];
        token_event.token_length = strlen(sample_tokens[i]);
        token_event.progress = (float)(i + 1) / num_tokens;
        token_event.tokens_so_far = i + 1;
        token_event.thermal_status = ainos_thermal_get_status();
        token_event.battery_level = g_ainos_state.battery_level;
        token_event.is_final = (i == num_tokens - 1);
        stream_callback(&token_event, user_data);

        ainos_sleep_impl(50); // Simulate time between tokens
    }

    // Send complete event
    ainos_stream_event_data_t complete_event;
    memset(&complete_event, 0, sizeof(complete_event));
    complete_event.event = AINOS_STREAM_EVENT_COMPLETE;
    complete_event.sequence = num_tokens + 1;
    complete_event.progress = 1.0f;
    complete_event.inference_time_ms = 800.0f;
    complete_event.tokens_so_far = num_tokens;
    complete_event.is_final = true;
    stream_callback(&complete_event, user_data);

    // Call completion callback
    if (completion_callback) {
        ainos_inference_result_t result;
        memset(&result, 0, sizeof(result));
        result.status = AINOS_OK;
        result.inference_time_ms = 800.0f;
        result.total_time_ms = 900.0f;
        result.tokens_generated = num_tokens;
        result.tokens_per_second = (num_tokens * 1000) / 900;
        result.thermal_status = ainos_thermal_get_status();
        result.battery_level = g_ainos_state.battery_level;
        completion_callback(AINOS_OK, &result, user_data);
    }

    return AINOS_OK;
}

ainos_status_t ainos_inference_cancel(const char* model_id)
{
    (void)model_id;
    AINOS_LOG_I("Inference", "Inference cancelled");
    return AINOS_OK;
}

ainos_status_t ainos_inference_cancel_stream(const char* model_id)
{
    (void)model_id;
    AINOS_LOG_I("Inference", "Stream cancelled");
    return AINOS_OK;
}

ainos_status_t ainos_inference_is_running(const char* model_id, bool* running)
{
    if (!model_id || !running) return AINOS_ERROR_INVALID_PARAM;
    (void)model_id;
    *running = false;
    return AINOS_OK;
}

ainos_inference_backend_t ainos_inference_get_active_backend(void)
{
    return AINOS_INFERENCE_BACKEND_CPU;
}

ainos_status_t ainos_inference_get_available_backends(
    ainos_inference_backend_t** backends,
    size_t* count)
{
    if (!backends || !count) return AINOS_ERROR_INVALID_PARAM;

    static ainos_inference_backend_t available_backends[] = {
        AINOS_INFERENCE_BACKEND_CPU,
        AINOS_INFERENCE_BACKEND_GPU,
        AINOS_INFERENCE_BACKEND_AUTO
    };
    *count = 3;
    *backends = (ainos_inference_backend_t*)malloc(sizeof(ainos_inference_backend_t) * (*count));
    if (!*backends) return AINOS_ERROR_OUT_OF_MEMORY;

    memcpy(*backends, available_backends, sizeof(ainos_inference_backend_t) * (*count));
    return AINOS_OK;
}

void ainos_inference_free_result(ainos_inference_result_t* result)
{
    if (result) {
        if (result->output_data) {
            free(result->output_data);
        }
        free(result);
    }
}

void ainos_inference_free_tensor(ainos_tensor_t* tensor)
{
    if (tensor) {
        if (tensor->data) {
            free(tensor->data);
        }
        free(tensor);
    }
}

/*============================================================================
 * Streaming Handler
 *============================================================================*/

static ainos_stream_id_t g_next_stream_id = 1;

ainos_status_t ainos_stream_open(
    const char* model_id,
    ainos_stream_id_t* stream_id,
    ainos_stream_callback_t stream_callback,
    void* user_data)
{
    if (!model_id || !stream_id || !stream_callback) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_model_entry_t* entry = find_model_entry(model_id);
    if (!entry) return AINOS_ERROR_MODEL_NOT_FOUND;

    *stream_id = g_next_stream_id++;
    if (g_next_stream_id == AINOS_STREAM_ID_INVALID) {
        g_next_stream_id = 1;
    }

    AINOS_LOG_I("Stream", "Stream opened: %llu for model %s", *stream_id, model_id);
    return AINOS_OK;
}

ainos_status_t ainos_stream_send(ainos_stream_id_t stream_id, const void* data, size_t size)
{
    if (!data || size == 0) return AINOS_ERROR_INVALID_PARAM;
    if (stream_id == AINOS_STREAM_ID_INVALID) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    AINOS_LOG_D("Stream", "Sent %zu bytes to stream %llu", size, stream_id);
    return AINOS_OK;
}

ainos_status_t ainos_stream_close(ainos_stream_id_t stream_id)
{
    if (stream_id == AINOS_STREAM_ID_INVALID) return AINOS_ERROR_INVALID_PARAM;
    AINOS_LOG_I("Stream", "Stream closed: %llu", stream_id);
    return AINOS_OK;
}

ainos_status_t ainos_stream_is_active(ainos_stream_id_t stream_id, bool* active)
{
    if (stream_id == AINOS_STREAM_ID_INVALID || !active) return AINOS_ERROR_INVALID_PARAM;
    *active = false;
    return AINOS_OK;
}

/*============================================================================
 * Daemon Communication
 *============================================================================*/

ainos_status_t ainos_daemon_connect(const char* host, uint16_t port, uint32_t timeout_ms)
{
    if (!host) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    if (g_ainos_state.daemon_connected) {
        return AINOS_ERROR_ALREADY_INITIALIZED;
    }

    strncpy(g_ainos_state.daemon_host, host, sizeof(g_ainos_state.daemon_host) - 1);
    g_ainos_state.daemon_port = port;

    AINOS_LOG_I("Daemon", "Connecting to daemon at %s:%d (timeout: %u ms)",
                host, port, timeout_ms);

    // Platform-specific connection
    g_ainos_state.daemon_connected = true;

    AINOS_LOG_I("Daemon", "Connected to daemon at %s:%d", host, port);

    if (g_ainos_state.daemon_connection_callback) {
        g_ainos_state.daemon_connection_callback(true, g_ainos_state.daemon_connection_userdata);
    }
    return AINOS_OK;
}

void ainos_daemon_disconnect(void)
{
    if (!g_ainos_state.daemon_connected) return;

    AINOS_LOG_I("Daemon", "Disconnecting from daemon");
    g_ainos_state.daemon_connected = false;

    if (g_ainos_state.daemon_connection_callback) {
        g_ainos_state.daemon_connection_callback(false, g_ainos_state.daemon_connection_userdata);
    }
}

bool ainos_daemon_is_connected(void)
{
    return g_ainos_state.daemon_connected;
}

ainos_status_t ainos_daemon_send_command(
    ainos_daemon_command_t command,
    const void* request,
    size_t request_size,
    void* response,
    size_t* response_size,
    uint32_t timeout_ms)
{
    if (!g_ainos_state.daemon_connected) return AINOS_ERROR_DAEMON_UNREACHABLE;
    if (!response || !response_size) return AINOS_ERROR_INVALID_PARAM;

    AINOS_LOG_D("Daemon", "Sending command 0x%04x (%zu bytes)", command, request_size);

    // Simulate daemon response
    memset(response, 0, *response_size);
    *response_size = 0;
    return AINOS_OK;
}

ainos_status_t ainos_daemon_send_async(
    const ainos_daemon_message_t* message,
    ainos_daemon_message_callback_t callback,
    void* user_data)
{
    if (!message) return AINOS_ERROR_INVALID_PARAM;
    if (!g_ainos_state.daemon_connected) return AINOS_ERROR_DAEMON_UNREACHABLE;

    AINOS_LOG_D("Daemon", "Sending async message 0x%04x", message->command);

    if (callback) {
        callback(message, user_data);
    }
    return AINOS_OK;
}

ainos_status_t ainos_daemon_register_connection_callback(
    ainos_daemon_connection_callback_t callback,
    void* user_data)
{
    if (!callback) return AINOS_ERROR_INVALID_PARAM;
    g_ainos_state.daemon_connection_callback = callback;
    g_ainos_state.daemon_connection_userdata = user_data;
    return AINOS_OK;
}

ainos_status_t ainos_daemon_get_status(ainos_daemon_status_t* status)
{
    if (!status) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    memset(status, 0, sizeof(*status));
    status->connected = g_ainos_state.daemon_connected;
    strncpy(status->daemon_version, "1.0.0", sizeof(status->daemon_version) - 1);
    strncpy(status->daemon_host, g_ainos_state.daemon_host, sizeof(status->daemon_host) - 1);
    status->daemon_port = g_ainos_state.daemon_port;
    status->uptime_seconds = 3600;
    status->active_clients = 1;
    status->last_heartbeat = ainos_get_timestamp_ms();
    status->thermal_status = ainos_thermal_get_status();
    ainos_battery_get_level(&status->battery_level);
    return AINOS_OK;
}

ainos_status_t ainos_daemon_send_heartbeat(void)
{
    if (!g_ainos_state.daemon_connected) return AINOS_ERROR_DAEMON_UNREACHABLE;

    AINOS_LOG_D("Daemon", "Heartbeat sent");
    return AINOS_OK;
}

/*============================================================================
 * Background Services
 *============================================================================*/

#define MAX_BACKGROUND_TASKS 32

typedef struct {
    ainos_background_task_config_t config;
    ainos_background_task_callback_t callback;
    void* user_data;
    bool running;
} ainos_background_task_t;

static ainos_background_task_t g_background_tasks[MAX_BACKGROUND_TASKS];
static int g_background_task_count = 0;

static ainos_background_task_t* find_background_task(const char* task_id)
{
    for (int i = 0; i < g_background_task_count; i++) {
        if (strcmp(g_background_tasks[i].config.task_id, task_id) == 0) {
            return &g_background_tasks[i];
        }
    }
    return NULL;
}

ainos_status_t ainos_background_register_task(
    const ainos_background_task_config_t* config,
    ainos_background_task_callback_t callback,
    void* user_data)
{
    if (!config || !callback) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    if (g_background_task_count >= MAX_BACKGROUND_TASKS) {
        return AINOS_ERROR_OUT_OF_MEMORY;
    }

    if (find_background_task(config->task_id)) {
        return AINOS_ERROR_ALREADY_INITIALIZED;
    }

    ainos_background_task_t* task = &g_background_tasks[g_background_task_count++];
    memcpy(&task->config, config, sizeof(ainos_background_task_config_t));
    task->callback = callback;
    task->user_data = user_data;
    task->running = false;

    AINOS_LOG_I("Background", "Registered task: %s (%s)", config->task_id, config->task_name);
    return AINOS_OK;
}

ainos_status_t ainos_background_unregister_task(const char* task_id)
{
    if (!task_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_background_task_t* task = find_background_task(task_id);
    if (!task) return AINOS_ERROR_GENERAL;

    // Remove by shifting
    int idx = (int)(task - g_background_tasks);
    if (idx < g_background_task_count - 1) {
        memmove(&g_background_tasks[idx], &g_background_tasks[idx + 1],
                (g_background_task_count - idx - 1) * sizeof(ainos_background_task_t));
    }
    g_background_task_count--;
    AINOS_LOG_I("Background", "Unregistered task: %s", task_id);
    return AINOS_OK;
}

ainos_status_t ainos_background_start_task(const char* task_id)
{
    if (!task_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_background_task_t* task = find_background_task(task_id);
    if (!task) return AINOS_ERROR_GENERAL;

    if (task->running) return AINOS_ERROR_BUSY;

    task->running = true;
    AINOS_LOG_I("Background", "Started task: %s", task_id);

    if (task->callback) {
        task->callback(task_id, AINOS_OK, task->user_data);
    }
    return AINOS_OK;
}

ainos_status_t ainos_background_stop_task(const char* task_id)
{
    if (!task_id) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_background_task_t* task = find_background_task(task_id);
    if (!task) return AINOS_ERROR_GENERAL;

    task->running = false;
    AINOS_LOG_I("Background", "Stopped task: %s", task_id);
    return AINOS_OK;
}

ainos_status_t ainos_background_task_status(const char* task_id, bool* running)
{
    if (!task_id || !running) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_background_task_t* task = find_background_task(task_id);
    if (!task) return AINOS_ERROR_GENERAL;

    *running = task->running;
    return AINOS_OK;
}

/*============================================================================
 * Push Notifications
 *============================================================================*/

ainos_status_t ainos_notification_show(const ainos_notification_t* notification)
{
    if (!notification) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    AINOS_LOG_I("Notifications", "Showing notification: %s - %s",
                notification->title, notification->body);
    return AINOS_OK;
}

ainos_status_t ainos_notification_cancel(const char* notification_id)
{
    if (!notification_id) return AINOS_ERROR_INVALID_PARAM;
    AINOS_LOG_I("Notifications", "Cancelled notification: %s", notification_id);
    return AINOS_OK;
}

ainos_status_t ainos_notification_cancel_all(void)
{
    AINOS_LOG_I("Notifications", "Cancelled all notifications");
    return AINOS_OK;
}

ainos_status_t ainos_notification_create_channel(
    const char* channel_id,
    const char* channel_name,
    int importance)
{
    if (!channel_id || !channel_name) return AINOS_ERROR_INVALID_PARAM;
    AINOS_LOG_I("Notifications", "Created channel: %s (%s) importance=%d",
                channel_id, channel_name, importance);
    return AINOS_OK;
}

ainos_status_t ainos_notification_delete_channel(const char* channel_id)
{
    if (!channel_id) return AINOS_ERROR_INVALID_PARAM;
    AINOS_LOG_I("Notifications", "Deleted channel: %s", channel_id);
    return AINOS_OK;
}

ainos_status_t ainos_notification_register_action_callback(
    ainos_notification_action_callback_t callback,
    void* user_data)
{
    if (!callback) return AINOS_ERROR_INVALID_PARAM;
    (void)user_data;
    AINOS_LOG_I("Notifications", "Registered action callback");
    return AINOS_OK;
}

ainos_status_t ainos_notification_schedule(const ainos_notification_t* notification)
{
    if (!notification) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    AINOS_LOG_I("Notifications", "Scheduled notification: %s for %lld",
                notification->title, notification->scheduled_time_ms);
    return AINOS_OK;
}

/*============================================================================
 * Foreground Service
 *============================================================================*/

ainos_status_t ainos_foreground_service_start(const ainos_foreground_service_config_t* config)
{
    if (!config) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    if (g_ainos_state.foreground_service_running) {
        return AINOS_ERROR_ALREADY_INITIALIZED;
    }

    g_ainos_state.foreground_service_running = true;
    g_ainos_state.foreground_notification_id = config->notification_id;

    AINOS_LOG_I("Foreground", "Foreground service started: %s", config->service_name);
    return AINOS_OK;
}

ainos_status_t ainos_foreground_service_stop(void)
{
    if (!g_ainos_state.foreground_service_running) {
        return AINOS_OK;
    }

    g_ainos_state.foreground_service_running = false;
    AINOS_LOG_I("Foreground", "Foreground service stopped");
    return AINOS_OK;
}

ainos_status_t ainos_foreground_service_update_notification(const char* title, const char* text)
{
    if (!title || !text) return AINOS_ERROR_INVALID_PARAM;
    if (!g_ainos_state.foreground_service_running) return AINOS_ERROR_GENERAL;

    AINOS_LOG_D("Foreground", "Notification updated: %s - %s", title, text);
    return AINOS_OK;
}

ainos_status_t ainos_foreground_service_is_running(bool* running)
{
    if (!running) return AINOS_ERROR_INVALID_PARAM;
    *running = g_ainos_state.foreground_service_running;
    return AINOS_OK;
}

/*============================================================================
 * Device Information
 *============================================================================*/

ainos_status_t ainos_device_get_info(ainos_device_info_t* info)
{
    if (!info) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    memset(info, 0, sizeof(*info));
    strncpy(info->device_model, "Ainos Device", sizeof(info->device_model) - 1);
    strncpy(info->device_manufacturer, "Ainos", sizeof(info->device_manufacturer) - 1);
    strncpy(info->os_version, "1.0", sizeof(info->os_version) - 1);
    strncpy(info->architecture, "arm64", sizeof(info->architecture) - 1);
    info->cpu_cores = 8;
    info->cpu_max_freq_mhz = 2800;
    info->cpu_min_freq_mhz = 300;
    info->total_ram_mb = 8192;
    info->available_ram_mb = 4096;
    info->total_storage_mb = 128000;
    info->available_storage_mb = 64000;
    info->is_emulator = false;
    info->has_npu = true;
    info->has_gpu = true;
    info->has_neural_engine = true;
    info->is_64bit = true;
    info->supports_fp16 = true;
    info->supports_int8 = true;
    info->battery_capacity_mah = 5000;

    return ainos_platform_impl_device_get_info(info);
}

ainos_status_t ainos_device_check_minimum_requirements(bool* meets_minimum)
{
    if (!meets_minimum) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    ainos_device_info_t info;
    ainos_status_t status = ainos_device_get_info(&info);
    if (status != AINOS_OK) return status;

    *meets_minimum = (info.total_ram_mb >= 4096 &&
                      info.cpu_cores >= 4 &&
                      info.available_storage_mb >= 2000);
    return AINOS_OK;
}

ainos_status_t ainos_device_get_api_level(int* api_level)
{
    if (!api_level) return AINOS_ERROR_INVALID_PARAM;
    if (!ainos_platform_check_initialized()) return AINOS_ERROR_NOT_INITIALIZED;

    if (g_ainos_state.platform_type != AINOS_PLATFORM_ANDROID) {
        return AINOS_ERROR_NOT_SUPPORTED;
    }
    *api_level = 33; // Android 13
    return AINOS_OK;
}

/*============================================================================
 * Utility Functions
 *============================================================================*/

const char* ainos_status_to_string(ainos_status_t status)
{
    switch (status) {
        case AINOS_OK:                        return "OK";
        case AINOS_ERROR_GENERAL:             return "General error";
        case AINOS_ERROR_INVALID_PARAM:       return "Invalid parameter";
        case AINOS_ERROR_OUT_OF_MEMORY:       return "Out of memory";
        case AINOS_ERROR_NOT_INITIALIZED:     return "Not initialized";
        case AINOS_ERROR_ALREADY_INITIALIZED: return "Already initialized";
        case AINOS_ERROR_TIMEOUT:             return "Timeout";
        case AINOS_ERROR_NETWORK:             return "Network error";
        case AINOS_ERROR_PERMISSION_DENIED:   return "Permission denied";
        case AINOS_ERROR_THERMAL_THROTTLED:   return "Thermal throttled";
        case AINOS_ERROR_BATTERY_LOW:         return "Battery low";
        case AINOS_ERROR_MODEL_NOT_FOUND:     return "Model not found";
        case AINOS_ERROR_MODEL_LOAD_FAILED:   return "Model load failed";
        case AINOS_ERROR_MODEL_INVALID:       return "Model invalid";
        case AINOS_ERROR_INFERENCE_FAILED:    return "Inference failed";
        case AINOS_ERROR_DAEMON_UNREACHABLE:  return "Daemon unreachable";
        case AINOS_ERROR_DAEMON_DISCONNECTED: return "Daemon disconnected";
        case AINOS_ERROR_STREAM_BUSY:         return "Stream busy";
        case AINOS_ERROR_STREAM_CLOSED:       return "Stream closed";
        case AINOS_ERROR_NOT_SUPPORTED:       return "Not supported";
        case AINOS_ERROR_BUSY:                return "Busy";
        case AINOS_ERROR_CANCELLED:           return "Cancelled";
        case AINOS_ERROR_STORAGE_FULL:        return "Storage full";
        case AINOS_ERROR_UPDATE_AVAILABLE:    return "Update available";
        case AINOS_ERROR_NEEDS_REBOOT:        return "Needs reboot";
        default:                              return "Unknown error";
    }
}

const char* ainos_thermal_status_to_string(ainos_thermal_status_t status)
{
    switch (status) {
        case AINOS_THERMAL_STATUS_NORMAL:    return "Normal";
        case AINOS_THERMAL_STATUS_WARM:      return "Warm";
        case AINOS_THERMAL_STATUS_HOT:       return "Hot";
        case AINOS_THERMAL_STATUS_CRITICAL:  return "Critical";
        case AINOS_THERMAL_STATUS_EMERGENCY: return "Emergency";
        case AINOS_THERMAL_STATUS_UNKNOWN:   return "Unknown";
        default:                             return "Unknown";
    }
}

const char* ainos_battery_status_to_string(ainos_battery_status_t status)
{
    switch (status) {
        case AINOS_BATTERY_STATUS_UNKNOWN:       return "Unknown";
        case AINOS_BATTERY_STATUS_CHARGING:      return "Charging";
        case AINOS_BATTERY_STATUS_DISCHARGING:   return "Discharging";
        case AINOS_BATTERY_STATUS_FULL:          return "Full";
        case AINOS_BATTERY_STATUS_NOT_CHARGING:  return "Not charging";
        default:                                 return "Unknown";
    }
}

void ainos_sleep(uint32_t ms)
{
    ainos_sleep_impl(ms);
}

int64_t ainos_get_timestamp_ms(void)
{
    return ainos_get_timestamp_ms_impl();
}

ainos_status_t ainos_generate_uuid(char* buffer, size_t buffer_size)
{
    if (!buffer || buffer_size < 37) return AINOS_ERROR_INVALID_PARAM;

    srand((unsigned int)(ainos_get_timestamp_ms() & 0xFFFFFFFF));
    const char* hex_chars = "0123456789abcdef";
    int pattern[36] = {
        8, 4, 4, 4, 12 // 8-4-4-4-12
    };
    int idx = 0;
    for (int i = 0; i < 5; i++) {
        if (i > 0) buffer[idx++] = '-';
        for (int j = 0; j < pattern[i]; j++) {
            if (idx == 12) {
                // Version 4
                buffer[idx++] = '4';
            } else if (idx == 16) {
                // Variant 10
                buffer[idx++] = (rand() % 4) == 0 ? '8' : (char)('9' + (rand() % 2));
            } else {
                buffer[idx++] = hex_chars[rand() % 16];
            }
        }
    }
    buffer[idx] = '\0';
    return AINOS_OK;
}

ainos_status_t ainos_mkdir_p(const char* path)
{
    if (!path) return AINOS_ERROR_INVALID_PARAM;

#ifdef _WIN32
    char tmp[512];
    strncpy(tmp, path, sizeof(tmp) - 1);
    for (char* p = tmp + 1; *p; p++) {
        if (*p == '/' || *p == '\\') {
            *p = '\0';
            _mkdir(tmp);
            *p = '/';
        }
    }
    _mkdir(tmp);
#else
    char tmp[512];
    strncpy(tmp, path, sizeof(tmp) - 1);
    for (char* p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    mkdir(tmp, 0755);
#endif
    return AINOS_OK;
}

bool ainos_file_exists(const char* path)
{
    if (!path) return false;
#ifdef _WIN32
    return _access(path, 0) == 0;
#else
    return access(path, F_OK) == 0;
#endif
}

ainos_status_t ainos_file_size(const char* path, uint64_t* size)
{
    if (!path || !size) return AINOS_ERROR_INVALID_PARAM;
#ifdef _WIN32
    struct _stat st;
    if (_stat(path, &st) != 0) return AINOS_ERROR_GENERAL;
#else
    struct stat st;
    if (stat(path, &st) != 0) return AINOS_ERROR_GENERAL;
#endif
    *size = (uint64_t)st.st_size;
    return AINOS_OK;
}

ainos_status_t ainos_file_delete(const char* path)
{
    if (!path) return AINOS_ERROR_INVALID_PARAM;
    if (remove(path) != 0) {
        return AINOS_ERROR_GENERAL;
    }
    return AINOS_OK;
}

ainos_status_t ainos_get_cache_dir(char* buffer, size_t buffer_size)
{
    if (!buffer) return AINOS_ERROR_INVALID_PARAM;
    return ainos_platform_impl_get_cache_dir(buffer, buffer_size);
}

ainos_status_t ainos_get_data_dir(char* buffer, size_t buffer_size)
{
    if (!buffer) return AINOS_ERROR_INVALID_PARAM;
    return ainos_platform_impl_get_data_dir(buffer, buffer_size);
}

const char* ainos_format_bytes(uint64_t bytes, char* buffer, size_t buffer_size)
{
    const char* units[] = {"B", "KB", "MB", "GB", "TB"};
    int unit_idx = 0;
    double size = (double)bytes;

    while (size >= 1024.0 && unit_idx < 4) {
        size /= 1024.0;
        unit_idx++;
    }

    snprintf(buffer, buffer_size, "%.2f %s", size, units[unit_idx]);
    return buffer;
}

ainos_status_t ainos_sha256_file(const char* path, char* hash_hex)
{
    if (!path || !hash_hex) return AINOS_ERROR_INVALID_PARAM;
    (void)path;
    // Placeholder - actual SHA-256 would use OpenSSL or platform crypto
    memset(hash_hex, '0', 64);
    hash_hex[64] = '\0';
    return AINOS_OK;
}

ainos_status_t ainos_base64_encode(
    const uint8_t* input,
    size_t input_size,
    char* output,
    size_t* output_size)
{
    if (!input || !output || !output_size) return AINOS_ERROR_INVALID_PARAM;

    static const char b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t encoded_size = ((input_size + 2) / 3) * 4;

    if (*output_size < encoded_size + 1) {
        *output_size = encoded_size + 1;
        return AINOS_ERROR_OUT_OF_MEMORY;
    }

    size_t i, j;
    for (i = 0, j = 0; i < input_size; i += 3) {
        uint32_t word = (uint32_t)input[i] << 16;
        if (i + 1 < input_size) word |= (uint32_t)input[i + 1] << 8;
        if (i + 2 < input_size) word |= (uint32_t)input[i + 2];

        output[j++] = b64[(word >> 18) & 0x3F];
        output[j++] = b64[(word >> 12) & 0x3F];
        output[j++] = (i + 1 < input_size) ? b64[(word >> 6) & 0x3F] : '=';
        output[j++] = (i + 2 < input_size) ? b64[word & 0x3F] : '=';
    }
    output[j] = '\0';
    *output_size = j;
    return AINOS_OK;
}

ainos_status_t ainos_base64_decode(
    const char* input,
    uint8_t* output,
    size_t* output_size)
{
    if (!input || !output || !output_size) return AINOS_ERROR_INVALID_PARAM;

    size_t input_len = strlen(input);
    if (input_len % 4 != 0) return AINOS_ERROR_INVALID_PARAM;

    size_t decoded_size = (input_len / 4) * 3;
    if (input[input_len - 1] == '=') decoded_size--;
    if (input_len > 1 && input[input_len - 2] == '=') decoded_size--;

    if (*output_size < decoded_size) {
        *output_size = decoded_size;
        return AINOS_ERROR_OUT_OF_MEMORY;
    }

    // Simple base64 decode
    size_t j = 0;
    for (size_t i = 0; i < input_len; i += 4) {
        uint32_t word = 0;
        for (int k = 0; k < 4; k++) {
            char c = input[i + k];
            uint32_t value;
            if (c >= 'A' && c <= 'Z') value = c - 'A';
            else if (c >= 'a' && c <= 'z') value = c - 'a' + 26;
            else if (c >= '0' && c <= '9') value = c - '0' + 52;
            else if (c == '+') value = 62;
            else if (c == '/') value = 63;
            else if (c == '=') value = 0;
            else return AINOS_ERROR_INVALID_PARAM;
            word = (word << 6) | value;
        }
        output[j++] = (uint8_t)((word >> 16) & 0xFF);
        if (j < decoded_size && input[i + 2] != '=') output[j++] = (uint8_t)((word >> 8) & 0xFF);
        if (j < decoded_size && input[i + 3] != '=') output[j++] = (uint8_t)(word & 0xFF);
    }

    *output_size = decoded_size;
    return AINOS_OK;
}

ainos_status_t ainos_compress(
    const uint8_t* input,
    size_t input_size,
    uint8_t** output,
    size_t* output_size)
{
    if (!input || !output || !output_size) return AINOS_ERROR_INVALID_PARAM;
    (void)input;
    (void)input_size;

    // Placeholder - actual compression would use zlib
    *output = (uint8_t*)malloc(input_size);
    if (!*output) return AINOS_ERROR_OUT_OF_MEMORY;
    memcpy(*output, input, input_size);
    *output_size = input_size;
    return AINOS_OK;
}

ainos_status_t ainos_decompress(
    const uint8_t* input,
    size_t input_size,
    uint8_t** output,
    size_t* output_size,
    size_t max_output_size)
{
    if (!input || !output || !output_size) return AINOS_ERROR_INVALID_PARAM;
    (void)max_output_size;

    *output = (uint8_t*)malloc(input_size);
    if (!*output) return AINOS_ERROR_OUT_OF_MEMORY;
    memcpy(*output, input, input_size);
    *output_size = input_size;
    return AINOS_OK;
}

/*============================================================================
 * Time Implementation
 *============================================================================*/

int64_t ainos_get_timestamp_ms_impl(void)
{
#ifdef _WIN32
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    t -= 116444736000000000ULL; // Convert to Unix epoch
    return (int64_t)(t / 10000);
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000 + (int64_t)tv.tv_usec / 1000;
#endif
}

void ainos_sleep_impl(uint32_t ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000;
    nanosleep(&ts, NULL);
#endif
}

/*============================================================================
 * String Utilities
 *============================================================================*/

const char* ainos_trim_whitespace(const char* str)
{
    if (!str) return NULL;
    while (*str == ' ' || *str == '\t' || *str == '\n' || *str == '\r') str++;
    return str;
}

int ainos_strcasecmp(const char* a, const char* b)
{
    if (!a || !b) return -1;
#ifdef _WIN32
    return _stricmp(a, b);
#else
    return strcasecmp(a, b);
#endif
}

char* ainos_strdup(const char* src)
{
    if (!src) return NULL;
    size_t len = strlen(src);
    char* dst = (char*)malloc(len + 1);
    if (dst) {
        memcpy(dst, src, len + 1);
    }
    return dst;
}

/*============================================================================
 * Platform-specific placeholder implementations
 * These are overridden by Android/iOS specific implementations
 *============================================================================*/

__attribute__((weak)) ainos_status_t ainos_platform_impl_init(void)
{
    return AINOS_OK;
}

__attribute__((weak)) void ainos_platform_impl_shutdown(void)
{
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_thermal_get_status(ainos_thermal_status_t* status)
{
    *status = AINOS_THERMAL_STATUS_NORMAL;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_thermal_get_cpu_temperature(float* temp)
{
    *temp = 35.0f;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_thermal_get_battery_temperature(float* temp)
{
    *temp = 30.0f;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_battery_get_level(int* level)
{
    *level = 80;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_battery_get_status(ainos_battery_status_t* status)
{
    *status = AINOS_BATTERY_STATUS_DISCHARGING;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_device_get_info(ainos_device_info_t* info)
{
    (void)info;
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_get_cache_dir(char* buffer, size_t size)
{
    const char* default_cache = "/tmp/ainos_cache";
    strncpy(buffer, default_cache, size - 1);
    buffer[size - 1] = '\0';
    return AINOS_OK;
}

__attribute__((weak)) ainos_status_t ainos_platform_impl_get_data_dir(char* buffer, size_t size)
{
    const char* default_data = "/tmp/ainos_data";
    strncpy(buffer, default_data, size - 1);
    buffer[size - 1] = '\0';
    return AINOS_OK;
}