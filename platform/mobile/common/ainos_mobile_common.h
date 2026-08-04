/**
 * ainos_mobile_common.h
 * Common shared header for Ainos mobile platform implementation
 *
 * Copyright (c) Ainos 2026
 */

#ifndef AINOS_MOBILE_COMMON_H
#define AINOS_MOBILE_COMMON_H

#include "ainos/platform_mobile.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/*============================================================================
 * Internal Logging
 *============================================================================*/

extern ainos_log_callback_t g_ainos_log_callback;

#define AINOS_LOG_V(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_VERBOSE, tag, _msg); \
        } \
    } while(0)

#define AINOS_LOG_D(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_DEBUG, tag, _msg); \
        } \
    } while(0)

#define AINOS_LOG_I(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_INFO, tag, _msg); \
        } \
    } while(0)

#define AINOS_LOG_W(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_WARN, tag, _msg); \
        } \
    } while(0)

#define AINOS_LOG_E(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_ERROR, tag, _msg); \
        } \
    } while(0)

#define AINOS_LOG_F(tag, ...) \
    do { \
        if (g_ainos_log_callback) { \
            char _msg[1024]; snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
            g_ainos_log_callback(AINOS_LOG_FATAL, tag, _msg); \
        } \
    } while(0)

/*============================================================================
 * Internal State
 *============================================================================*/

typedef struct {
    bool initialized;
    char app_name[128];
    char app_version[64];
    ainos_platform_type_t platform_type;
    ainos_thermal_status_t thermal_status;
    ainos_battery_status_t battery_status;
    int battery_level;
    ainos_power_mode_t power_mode;
    bool daemon_connected;
    char daemon_host[256];
    uint16_t daemon_port;
    uint64_t message_sequence;
    // Model cache state
    char model_cache_dir[512];
    uint32_t max_cache_size_mb;
    // Foreground service
    bool foreground_service_running;
    int foreground_notification_id;
    // Callbacks
    void (*thermal_callback)(ainos_thermal_status_t, ainos_thermal_status_t, void*);
    void* thermal_callback_userdata;
    void (*battery_callback)(ainos_battery_status_t, int, void*);
    void* battery_callback_userdata;
    ainos_daemon_connection_callback_t daemon_connection_callback;
    void* daemon_connection_userdata;
} ainos_platform_state_t;

extern ainos_platform_state_t g_ainos_state;

/*============================================================================
 * Internal helpers
 *============================================================================*/

/**
 * Check if platform is initialized, log error if not.
 */
bool ainos_platform_check_initialized(void);

/**
 * Thread-safe time utilities.
 */
int64_t ainos_get_timestamp_ms_impl(void);
void ainos_sleep_impl(uint32_t ms);

/**
 * Platform-specific implementations (declared here, defined per-platform).
 */
ainos_status_t ainos_platform_impl_init(void);
void ainos_platform_impl_shutdown(void);
ainos_status_t ainos_platform_impl_thermal_get_status(ainos_thermal_status_t* status);
ainos_status_t ainos_platform_impl_thermal_get_cpu_temperature(float* temp);
ainos_status_t ainos_platform_impl_thermal_get_battery_temperature(float* temp);
ainos_status_t ainos_platform_impl_battery_get_level(int* level);
ainos_status_t ainos_platform_impl_battery_get_status(ainos_battery_status_t* status);
ainos_status_t ainos_platform_impl_device_get_info(ainos_device_info_t* info);
ainos_status_t ainos_platform_impl_get_cache_dir(char* buffer, size_t size);
ainos_status_t ainos_platform_impl_get_data_dir(char* buffer, size_t size);

/*============================================================================
 * String utilities
 *============================================================================*/

const char* ainos_trim_whitespace(const char* str);
int ainos_strcasecmp(const char* a, const char* b);
char* ainos_strdup(const char* src);

#ifdef __cplusplus
}
#endif

#endif /* AINOS_MOBILE_COMMON_H */