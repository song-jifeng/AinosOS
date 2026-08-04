/**
 * ainos_android_platform.cpp
 * Android platform implementation for Ainos
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos_mobile_common.h"
#include <jni.h>
#include <android/log.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pthread.h>
#include <errno.h>

#define LOG_TAG "AinosAndroid"

/*============================================================================
 * JVM Reference
 *============================================================================*/

static JavaVM* g_jvm = NULL;
static JNIEnv* g_main_env = NULL;
static jclass g_ainos_native_class = NULL;
static jclass g_ainos_service_class = NULL;
static jclass g_model_info_class = NULL;
static jclass g_inference_result_class = NULL;
static jobject g_ainos_service_obj = NULL;
static jobject g_ainos_native_obj = NULL;

/*============================================================================
 * Thermal Monitoring State
 *============================================================================*/

typedef struct {
    pthread_t thread;
    bool running;
    int interval_ms;
    int current_temp_celsius;
    ainos_thermal_status_t current_status;
    float cpu_temperature;
    float battery_temperature;
} android_thermal_state_t;

static android_thermal_state_t g_thermal_state = {
    .thread = 0,
    .running = false,
    .interval_ms = 5000,
    .current_temp_celsius = 35,
    .current_status = AINOS_THERMAL_STATUS_NORMAL,
    .cpu_temperature = 35.0f,
    .battery_temperature = 30.0f
};

static pthread_mutex_t g_thermal_mutex = PTHREAD_MUTEX_INITIALIZER;

/*============================================================================
 * Battery Monitoring State
 *============================================================================*/

typedef struct {
    pthread_t thread;
    bool running;
    int interval_ms;
    int current_level;
    ainos_battery_status_t current_status;
    bool is_charging;
} android_battery_state_t;

static android_battery_state_t g_battery_state = {
    .thread = 0,
    .running = false,
    .interval_ms = 10000,
    .current_level = 80,
    .current_status = AINOS_BATTERY_STATUS_DISCHARGING,
    .is_charging = false
};

static pthread_mutex_t g_battery_mutex = PTHREAD_MUTEX_INITIALIZER;

/*============================================================================
 * JNI Helpers
 *============================================================================*/

static JNIEnv* get_jni_env(void)
{
    JNIEnv* env = NULL;
    if (g_jvm) {
        int get_env_result = (*g_jvm)->GetEnv(g_jvm, (void**)&env, JNI_VERSION_1_6);
        if (get_env_result == JNI_EDETACHED) {
            if ((*g_jvm)->AttachCurrentThread(g_jvm, &env, NULL) != JNI_OK) {
                __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                                    "Failed to attach thread to JVM");
                return NULL;
            }
        }
    }
    return env;
}

static void detach_jni_thread(void)
{
    if (g_jvm) {
        (*g_jvm)->DetachCurrentThread(g_jvm);
    }
}

static jstring string_to_jstring(JNIEnv* env, const char* str)
{
    if (!str) return NULL;
    return (*env)->NewStringUTF(env, str);
}

static char* jstring_to_string(JNIEnv* env, jstring jstr)
{
    if (!jstr) return NULL;
    const char* utf = (*env)->GetStringUTFChars(env, jstr, NULL);
    if (!utf) return NULL;
    char* result = strdup(utf);
    (*env)->ReleaseStringUTFChars(env, jstr, utf);
    return result;
}

/*============================================================================
 * Thermal Monitoring Thread
 *============================================================================*/

static void* thermal_monitor_thread(void* arg)
{
    (void)arg;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "Thermal monitor thread started");

    // Read thermal zones from sysfs
    // Common paths: /sys/class/thermal/thermal_zone*/temp
    const char* thermal_zone_paths[] = {
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/thermal/thermal_zone2/temp",
        "/sys/class/thermal/thermal_zone3/temp",
        "/sys/class/thermal/thermal_zone4/temp",
        "/sys/class/thermal/thermal_zone5/temp",
        "/sys/class/thermal/thermal_zone6/temp",
        "/sys/class/thermal/thermal_zone7/temp",
        "/sys/class/thermal/thermal_zone8/temp",
        "/sys/class/thermal/thermal_zone9/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
        NULL
    };

    // Battery temperature paths
    const char* batt_temp_paths[] = {
        "/sys/class/power_supply/battery/temp",
        "/sys/class/power_supply/Battery/temp",
        "/sys/devices/platform/battery/temp",
        NULL
    };

    while (g_thermal_state.running) {
        float max_cpu_temp = 0.0f;
        float battery_temp = 0.0f;

        // Read CPU temperatures
        for (int i = 0; thermal_zone_paths[i] != NULL; i++) {
            FILE* fp = fopen(thermal_zone_paths[i], "r");
            if (fp) {
                int temp_raw = 0;
                if (fscanf(fp, "%d", &temp_raw) == 1) {
                    float temp_c = temp_raw / 1000.0f;
                    if (temp_c > max_cpu_temp) {
                        max_cpu_temp = temp_c;
                    }
                }
                fclose(fp);
            }
        }

        // Read battery temperature
        for (int i = 0; batt_temp_paths[i] != NULL; i++) {
            FILE* fp = fopen(batt_temp_paths[i], "r");
            if (fp) {
                int temp_raw = 0;
                if (fscanf(fp, "%d", &temp_raw) == 1) {
                    battery_temp = temp_raw / 10.0f;
                    if (battery_temp > 0) break;
                }
                fclose(fp);
            }
        }

        pthread_mutex_lock(&g_thermal_mutex);
        g_thermal_state.cpu_temperature = max_cpu_temp;
        g_thermal_state.battery_temperature = battery_temp;

        // Determine thermal status
        ainos_thermal_status_t old_status = g_thermal_state.current_status;
        if (max_cpu_temp >= 85.0f || battery_temp >= 55.0f) {
            g_thermal_state.current_status = AINOS_THERMAL_STATUS_EMERGENCY;
        } else if (max_cpu_temp >= 75.0f || battery_temp >= 48.0f) {
            g_thermal_state.current_status = AINOS_THERMAL_STATUS_CRITICAL;
        } else if (max_cpu_temp >= 65.0f || battery_temp >= 42.0f) {
            g_thermal_state.current_status = AINOS_THERMAL_STATUS_HOT;
        } else if (max_cpu_temp >= 55.0f || battery_temp >= 38.0f) {
            g_thermal_state.current_status = AINOS_THERMAL_STATUS_WARM;
        } else {
            g_thermal_state.current_status = AINOS_THERMAL_STATUS_NORMAL;
        }

        ainos_thermal_status_t new_status = g_thermal_state.current_status;
        pthread_mutex_unlock(&g_thermal_mutex);

        // Update global state
        g_ainos_state.thermal_status = new_status;

        // Fire callback if status changed
        if (old_status != new_status && g_ainos_state.thermal_callback) {
            g_ainos_state.thermal_callback(old_status, new_status,
                                            g_ainos_state.thermal_callback_userdata);
        }

        // Log temperature changes
        if (g_thermal_state.cpu_temperature > 50.0f) {
            __android_log_print(ANDROID_LOG_WARN, LOG_TAG,
                                "Thermal: CPU=%.1fC Battery=%.1fC Status=%d",
                                max_cpu_temp, battery_temp, new_status);
        }

        usleep(g_thermal_state.interval_ms * 1000);
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "Thermal monitor thread stopped");
    return NULL;
}

/*============================================================================
 * Battery Monitoring Thread
 *============================================================================*/

static void* battery_monitor_thread(void* arg)
{
    (void)arg;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "Battery monitor thread started");

    const char* capacity_paths[] = {
        "/sys/class/power_supply/battery/capacity",
        "/sys/class/power_supply/Battery/capacity",
        "/sys/devices/platform/battery/capacity",
        NULL
    };

    const char* status_paths[] = {
        "/sys/class/power_supply/battery/status",
        "/sys/class/power_supply/Battery/status",
        "/sys/devices/platform/battery/status",
        NULL
    };

    while (g_battery_state.running) {
        int level = -1;
        ainos_battery_status_t status = AINOS_BATTERY_STATUS_UNKNOWN;

        // Read battery capacity
        for (int i = 0; capacity_paths[i] != NULL; i++) {
            FILE* fp = fopen(capacity_paths[i], "r");
            if (fp) {
                if (fscanf(fp, "%d", &level) == 1) {
                    fclose(fp);
                    break;
                }
                fclose(fp);
            }
        }

        // Read battery status
        for (int i = 0; status_paths[i] != NULL; i++) {
            FILE* fp = fopen(status_paths[i], "r");
            if (fp) {
                char buf[32];
                if (fgets(buf, sizeof(buf), fp)) {
                    // Remove newline
                    size_t len = strlen(buf);
                    if (len > 0 && buf[len-1] == '\n') buf[len-1] = '\0';

                    if (strcmp(buf, "Charging") == 0) {
                        status = AINOS_BATTERY_STATUS_CHARGING;
                    } else if (strcmp(buf, "Discharging") == 0) {
                        status = AINOS_BATTERY_STATUS_DISCHARGING;
                    } else if (strcmp(buf, "Full") == 0) {
                        status = AINOS_BATTERY_STATUS_FULL;
                    } else if (strcmp(buf, "Not charging") == 0) {
                        status = AINOS_BATTERY_STATUS_NOT_CHARGING;
                    } else {
                        status = AINOS_BATTERY_STATUS_UNKNOWN;
                    }
                    fclose(fp);
                    break;
                }
                fclose(fp);
            }
        }

        if (level < 0) level = 80; // Default fallback

        pthread_mutex_lock(&g_battery_mutex);
        g_battery_state.current_level = level;
        g_battery_state.current_status = status;
        g_battery_state.is_charging = (status == AINOS_BATTERY_STATUS_CHARGING ||
                                        status == AINOS_BATTERY_STATUS_FULL);
        pthread_mutex_unlock(&g_battery_mutex);

        // Update global state
        g_ainos_state.battery_level = level;
        g_ainos_state.battery_status = status;

        // Fire callback
        if (g_ainos_state.battery_callback) {
            g_ainos_state.battery_callback(status, level,
                                            g_ainos_state.battery_callback_userdata);
        }

        // Log low battery
        if (level >= 0 && level <= 15) {
            __android_log_print(ANDROID_LOG_WARN, LOG_TAG,
                                "Battery low: %d%%", level);
        }

        usleep(g_battery_state.interval_ms * 1000);
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "Battery monitor thread stopped");
    return NULL;
}

/*============================================================================
 * Platform Implementation
 *============================================================================*/

ainos_status_t ainos_platform_impl_init(void)
{
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Android platform initializing");

    // Start thermal monitoring
    g_thermal_state.running = true;
    if (pthread_create(&g_thermal_state.thread, NULL,
                       thermal_monitor_thread, NULL) != 0) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "Failed to create thermal monitor thread");
        g_thermal_state.running = false;
    } else {
        pthread_detach(g_thermal_state.thread);
    }

    // Start battery monitoring
    g_battery_state.running = true;
    if (pthread_create(&g_battery_state.thread, NULL,
                       battery_monitor_thread, NULL) != 0) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "Failed to create battery monitor thread");
        g_battery_state.running = false;
    } else {
        pthread_detach(g_battery_state.thread);
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Android platform initialized successfully");
    return AINOS_OK;
}

void ainos_platform_impl_shutdown(void)
{
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Android platform shutting down");

    // Stop thermal monitoring
    if (g_thermal_state.running) {
        g_thermal_state.running = false;
        pthread_join(g_thermal_state.thread, NULL);
    }

    // Stop battery monitoring
    if (g_battery_state.running) {
        g_battery_state.running = false;
        pthread_join(g_battery_state.thread, NULL);
    }

    // Cleanup JNI references
    JNIEnv* env = get_jni_env();
    if (env) {
        if (g_ainos_native_class) {
            (*env)->DeleteGlobalRef(env, g_ainos_native_class);
            g_ainos_native_class = NULL;
        }
        if (g_ainos_service_class) {
            (*env)->DeleteGlobalRef(env, g_ainos_service_class);
            g_ainos_service_class = NULL;
        }
        if (g_ainos_service_obj) {
            (*env)->DeleteGlobalRef(env, g_ainos_service_obj);
            g_ainos_service_obj = NULL;
        }
        if (g_ainos_native_obj) {
            (*env)->DeleteGlobalRef(env, g_ainos_native_obj);
            g_ainos_native_obj = NULL;
        }
    }

    pthread_mutex_destroy(&g_thermal_mutex);
    pthread_mutex_destroy(&g_battery_mutex);

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Android platform shutdown complete");
}

/*============================================================================
 * Thermal Status
 *============================================================================*/

ainos_status_t ainos_platform_impl_thermal_get_status(ainos_thermal_status_t* status)
{
    pthread_mutex_lock(&g_thermal_mutex);
    *status = g_thermal_state.current_status;
    pthread_mutex_unlock(&g_thermal_mutex);
    return AINOS_OK;
}

ainos_status_t ainos_platform_impl_thermal_get_cpu_temperature(float* temp)
{
    pthread_mutex_lock(&g_thermal_mutex);
    *temp = g_thermal_state.cpu_temperature;
    pthread_mutex_unlock(&g_thermal_mutex);
    return AINOS_OK;
}

ainos_status_t ainos_platform_impl_thermal_get_battery_temperature(float* temp)
{
    pthread_mutex_lock(&g_thermal_mutex);
    *temp = g_thermal_state.battery_temperature;
    pthread_mutex_unlock(&g_thermal_mutex);
    return AINOS_OK;
}

/*============================================================================
 * Battery Status
 *============================================================================*/

ainos_status_t ainos_platform_impl_battery_get_level(int* level)
{
    pthread_mutex_lock(&g_battery_mutex);
    *level = g_battery_state.current_level;
    pthread_mutex_unlock(&g_battery_mutex);
    return AINOS_OK;
}

ainos_status_t ainos_platform_impl_battery_get_status(ainos_battery_status_t* status)
{
    pthread_mutex_lock(&g_battery_mutex);
    *status = g_battery_state.current_status;
    pthread_mutex_unlock(&g_battery_mutex);
    return AINOS_OK;
}

/*============================================================================
 * Device Info
 *============================================================================*/

ainos_status_t ainos_platform_impl_device_get_info(ainos_device_info_t* info)
{
    // Read CPU info
    FILE* fp = fopen("/proc/cpuinfo", "r");
    if (fp) {
        char line[256];
        int cores = 0;
        while (fgets(line, sizeof(line), fp)) {
            if (strstr(line, "processor")) {
                cores++;
            }
        }
        fclose(fp);
        if (cores > 0) info->cpu_cores = cores;
    }

    // Read CPU max frequency
    fp = fopen("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "r");
    if (fp) {
        int freq_khz = 0;
        if (fscanf(fp, "%d", &freq_khz) == 1) {
            info->cpu_max_freq_mhz = freq_khz / 1000;
        }
        fclose(fp);
    }

    // Read CPU min frequency
    fp = fopen("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq", "r");
    if (fp) {
        int freq_khz = 0;
        if (fscanf(fp, "%d", &freq_khz) == 1) {
            info->cpu_min_freq_mhz = freq_khz / 1000;
        }
        fclose(fp);
    }

    // Read memory info
    fp = fopen("/proc/meminfo", "r");
    if (fp) {
        char line[256];
        while (fgets(line, sizeof(line), fp)) {
            if (sscanf(line, "MemTotal: %llu kB", &info->total_ram_mb) == 1) {
                info->total_ram_mb /= 1024;
            } else if (sscanf(line, "MemAvailable: %llu kB", &info->available_ram_mb) == 1) {
                info->available_ram_mb /= 1024;
            }
        }
        fclose(fp);
    }

    // Read kernel version
    fp = fopen("/proc/version", "r");
    if (fp) {
        if (fgets(info->os_version, sizeof(info->os_version) - 1, fp)) {
            // Truncate to first newline
            char* nl = strchr(info->os_version, '\n');
            if (nl) *nl = '\0';
        }
        fclose(fp);
    }

    // Check for NPU
    info->has_npu = (access("/dev/accelerator", F_OK) == 0 ||
                     access("/dev/vendor_npu", F_OK) == 0 ||
                     access("/dev/ion", F_OK) == 0);

    // Check for GPU
    info->has_gpu = (access("/dev/dri/card0", F_OK) == 0 ||
                     access("/dev/kgsl-3d0", F_OK) == 0);

    // Read system properties for build info
    info->is_64bit = (sizeof(void*) == 8);
    info->supports_fp16 = true;
    info->supports_int8 = true;

    // Read battery capacity
    fp = fopen("/sys/class/power_supply/battery/charge_full", "r");
    if (fp) {
        int uah = 0;
        if (fscanf(fp, "%d", &uah) == 1) {
            info->battery_capacity_mah = uah / 1000;
        }
        fclose(fp);
    }

    // Read screen info
    fp = fopen("/sys/class/graphics/fb0/virtual_size", "r");
    if (fp) {
        fscanf(fp, "%u,%u", &info->screen_width_px, &info->screen_height_px);
        fclose(fp);
    }

    if (info->screen_width_px == 0) {
        info->screen_width_px = 1080;
        info->screen_height_px = 2400;
    }
    info->screen_density = 2.75f; // ~440 dpi
    info->screen_refresh_rate = 60.0f;

    strncpy(info->android_api_level, "33", sizeof(info->android_api_level) - 1);
    strncpy(info->device_manufacturer, "Ainos", sizeof(info->device_manufacturer) - 1);
    strncpy(info->device_model, "Ainos Mobile", sizeof(info->device_model) - 1);
    strncpy(info->architecture, sizeof(void*) == 8 ? "arm64" : "arm",
            sizeof(info->architecture) - 1);

    return AINOS_OK;
}

/*============================================================================
 * Cache & Data Directories
 *============================================================================*/

ainos_status_t ainos_platform_impl_get_cache_dir(char* buffer, size_t size)
{
    if (g_ainos_service_obj) {
        JNIEnv* env = get_jni_env();
        if (env) {
            jclass cls = (*env)->GetObjectClass(env, g_ainos_service_obj);
            if (cls) {
                jmethodID mid = (*env)->GetMethodID(env, cls, "getCacheDir",
                                                     "()Ljava/io/File;");
                if (mid) {
                    jobject file_obj = (*env)->CallObjectMethod(env, g_ainos_service_obj, mid);
                    if (file_obj) {
                        jclass file_cls = (*env)->GetObjectClass(env, file_obj);
                        jmethodID path_mid = (*env)->GetMethodID(env, file_cls,
                                                                  "getAbsolutePath",
                                                                  "()Ljava/lang/String;");
                        jstring path_str = (*env)->CallObjectMethod(env, file_obj, path_mid);
                        const char* path = (*env)->GetStringUTFChars(env, path_str, NULL);
                        strncpy(buffer, path, size - 1);
                        buffer[size - 1] = '\0';
                        (*env)->ReleaseStringUTFChars(env, path_str, path);
                        (*env)->DeleteLocalRef(env, path_str);
                        (*env)->DeleteLocalRef(env, file_cls);
                        (*env)->DeleteLocalRef(env, file_obj);
                        (*env)->DeleteLocalRef(env, cls);
                        return AINOS_OK;
                    }
                    (*env)->DeleteLocalRef(env, file_obj);
                }
                (*env)->DeleteLocalRef(env, cls);
            }
        }
    }

    // Fallback
    strncpy(buffer, "/data/data/com.ainos/cache", size - 1);
    buffer[size - 1] = '\0';
    return AINOS_OK;
}

ainos_status_t ainos_platform_impl_get_data_dir(char* buffer, size_t size)
{
    if (g_ainos_service_obj) {
        JNIEnv* env = get_jni_env();
        if (env) {
            jclass cls = (*env)->GetObjectClass(env, g_ainos_service_obj);
            if (cls) {
                jmethodID mid = (*env)->GetMethodID(env, cls, "getFilesDir",
                                                     "()Ljava/io/File;");
                if (mid) {
                    jobject file_obj = (*env)->CallObjectMethod(env, g_ainos_service_obj, mid);
                    if (file_obj) {
                        jclass file_cls = (*env)->GetObjectClass(env, file_obj);
                        jmethodID path_mid = (*env)->GetMethodID(env, file_cls,
                                                                  "getAbsolutePath",
                                                                  "()Ljava/lang/String;");
                        jstring path_str = (*env)->CallObjectMethod(env, file_obj, path_mid);
                        const char* path = (*env)->GetStringUTFChars(env, path_str, NULL);
                        strncpy(buffer, path, size - 1);
                        buffer[size - 1] = '\0';
                        (*env)->ReleaseStringUTFChars(env, path_str, path);
                        (*env)->DeleteLocalRef(env, path_str);
                        (*env)->DeleteLocalRef(env, file_cls);
                        (*env)->DeleteLocalRef(env, file_obj);
                        (*env)->DeleteLocalRef(env, cls);
                        return AINOS_OK;
                    }
                    (*env)->DeleteLocalRef(env, file_obj);
                }
                (*env)->DeleteLocalRef(env, cls);
            }
        }
    }

    strncpy(buffer, "/data/data/com.ainos/files", size - 1);
    buffer[size - 1] = '\0';
    return AINOS_OK;
}

/*============================================================================
 * JNI Initialization
 *============================================================================*/

void ainos_android_set_jvm(JavaVM* jvm)
{
    g_jvm = jvm;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "JVM reference set: %p", jvm);
}

JavaVM* ainos_android_get_jvm(void)
{
    return g_jvm;
}

void ainos_android_set_service_object(jobject service_obj)
{
    JNIEnv* env = get_jni_env();
    if (env) {
        if (g_ainos_service_obj) {
            (*env)->DeleteGlobalRef(env, g_ainos_service_obj);
        }
        g_ainos_service_obj = (*env)->NewGlobalRef(env, service_obj);
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                            "Service object set: %p", service_obj);
    }
}

jobject ainos_android_get_service_object(void)
{
    return g_ainos_service_obj;
}

/*============================================================================
 * JNI Registration
 *============================================================================*/

static jint android_get_api_level(JNIEnv* env, jclass clazz)
{
    (void)clazz;
    int api_level = 0;
    char prop_value[8] = {0};

    FILE* fp = popen("getprop ro.build.version.sdk", "r");
    if (fp) {
        if (fgets(prop_value, sizeof(prop_value), fp)) {
            api_level = atoi(prop_value);
        }
        pclose(fp);
    }

    if (api_level == 0) {
        // Fallback: try parsing build.prop
        fp = fopen("/system/build.prop", "r");
        if (fp) {
            char line[256];
            while (fgets(line, sizeof(line), fp)) {
                if (sscanf(line, "ro.build.version.sdk=%d", &api_level) == 1) {
                    break;
                }
            }
            fclose(fp);
        }
    }

    return (jint)api_level;
}

static jint android_get_thermal_status(JNIEnv* env, jclass clazz)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_thermal_get_status();
}

static jint android_get_battery_level(JNIEnv* env, jclass clazz)
{
    (void)env;
    (void)clazz;
    int level;
    ainos_battery_get_level(&level);
    return (jint)level;
}

static jboolean android_is_charging(JNIEnv* env, jclass clazz)
{
    (void)env;
    (void)clazz;
    return ainos_battery_is_charging() ? JNI_TRUE : JNI_FALSE;
}

static jstring android_get_device_info(JNIEnv* env, jclass clazz)
{
    (void)clazz;
    ainos_device_info_t info;
    ainos_device_get_info(&info);

    char json[2048];
    snprintf(json, sizeof(json),
             "{\"model\":\"%s\",\"manufacturer\":\"%s\",\"os_version\":\"%s\","
             "\"cpu_cores\":%u,\"total_ram_mb\":%llu,\"available_ram_mb\":%llu,"
             "\"has_npu\":%s,\"has_gpu\":%s,\"battery_capacity_mah\":%u}",
             info.device_model, info.device_manufacturer, info.os_version,
             info.cpu_cores, info.total_ram_mb, info.available_ram_mb,
             info.has_npu ? "true" : "false",
             info.has_gpu ? "true" : "false",
             info.battery_capacity_mah);

    return (*env)->NewStringUTF(env, json);
}

static jint android_connect_daemon(JNIEnv* env, jclass clazz,
                                    jstring host, jint port, jint timeout_ms)
{
    (void)env;
    (void)clazz;
    const char* host_str = (*env)->GetStringUTFChars(env, host, NULL);
    ainos_status_t status = ainos_daemon_connect(host_str, (uint16_t)port, (uint32_t)timeout_ms);
    (*env)->ReleaseStringUTFChars(env, host, host_str);
    return (jint)status;
}

static jint android_send_daemon_command(JNIEnv* env, jclass clazz,
                                         jint command, jbyteArray request_data,
                                         jbyteArray response_data)
{
    (void)env;
    (void)clazz;
    (void)command;
    (void)request_data;
    (void)response_data;
    return (jint)AINOS_OK;
}

static jint android_start_foreground_service(JNIEnv* env, jclass clazz,
                                              jint notification_id,
                                              jstring channel_id,
                                              jstring title,
                                              jstring text)
{
    (void)env;
    (void)clazz;
    (void)notification_id;
    (void)channel_id;
    (void)title;
    (void)text;

    ainos_foreground_service_config_t config;
    memset(&config, 0, sizeof(config));
    config.notification_id = (int)notification_id;
    config.show_foreground_notification = true;
    config.keep_alive = true;
    config.keep_alive_interval_ms = 30000;

    const char* title_str = (*env)->GetStringUTFChars(env, title, NULL);
    const char* text_str = (*env)->GetStringUTFChars(env, text, NULL);
    strncpy(config.notification_title, title_str, sizeof(config.notification_title) - 1);
    strncpy(config.notification_text, text_str, sizeof(config.notification_text) - 1);
    (*env)->ReleaseStringUTFChars(env, title, title_str);
    (*env)->ReleaseStringUTFChars(env, text, text_str);

    ainos_status_t status = ainos_foreground_service_start(&config);
    return (jint)status;
}

static jint android_stop_foreground_service(JNIEnv* env, jclass clazz)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_foreground_service_stop();
}

static jint android_show_notification(JNIEnv* env, jclass clazz,
                                       jstring title, jstring body,
                                       jint priority)
{
    (void)env;
    (void)clazz;

    ainos_notification_t notif;
    memset(&notif, 0, sizeof(notif));
    strncpy(notif.notification_id, "android_notification", sizeof(notif.notification_id) - 1);
    const char* title_str = (*env)->GetStringUTFChars(env, title, NULL);
    const char* body_str = (*env)->GetStringUTFChars(env, body, NULL);
    strncpy(notif.title, title_str, sizeof(notif.title) - 1);
    strncpy(notif.body, body_str, sizeof(notif.body) - 1);
    (*env)->ReleaseStringUTFChars(env, title, title_str);
    (*env)->ReleaseStringUTFChars(env, body, body_str);
    notif.priority = (ainos_notification_priority_t)priority;
    notif.auto_cancel = true;
    notif.show_timestamp = true;
    notif.vibrate = true;

    return (jint)ainos_notification_show(&notif);
}

static jint android_model_download(JNIEnv* env, jclass clazz, jstring model_id)
{
    (void)env;
    (void)clazz;
    const char* model_id_str = (*env)->GetStringUTFChars(env, model_id, NULL);
    ainos_status_t status = ainos_model_download(model_id_str, NULL, NULL);
    (*env)->ReleaseStringUTFChars(env, model_id, model_id_str);
    return (jint)status;
}

static jint android_model_load(JNIEnv* env, jclass clazz, jstring model_id)
{
    (void)env;
    (void)clazz;
    const char* model_id_str = (*env)->GetStringUTFChars(env, model_id, NULL);
    ainos_status_t status = ainos_model_load(model_id_str, NULL, NULL);
    (*env)->ReleaseStringUTFChars(env, model_id, model_id_str);
    return (jint)status;
}

static jint android_model_unload(JNIEnv* env, jclass clazz, jstring model_id)
{
    (void)env;
    (void)clazz;
    const char* model_id_str = (*env)->GetStringUTFChars(env, model_id, NULL);
    ainos_status_t status = ainos_model_unload(model_id_str);
    (*env)->ReleaseStringUTFChars(env, model_id, model_id_str);
    return (jint)status;
}

static jint android_run_inference(JNIEnv* env, jclass clazz,
                                   jstring model_id, jbyteArray input_data,
                                   jbyteArray output_data)
{
    (void)env;
    (void)clazz;
    (void)model_id;
    (void)input_data;
    (void)output_data;
    return (jint)AINOS_OK;
}

static jint android_init(JNIEnv* env, jclass clazz, jstring app_name, jstring app_version)
{
    const char* name = (*env)->GetStringUTFChars(env, app_name, NULL);
    const char* version = (*env)->GetStringUTFChars(env, app_version, NULL);
    ainos_status_t status = ainos_platform_init(name, version, NULL);
    (*env)->ReleaseStringUTFChars(env, app_name, name);
    (*env)->ReleaseStringUTFChars(env, app_version, version);
    return (jint)status;
}

static void android_shutdown(JNIEnv* env, jclass clazz)
{
    (void)env;
    (void)clazz;
    ainos_platform_shutdown();
}

/*============================================================================
 * JNI Method Table
 *============================================================================*/

static const JNINativeMethod g_native_methods[] = {
    {"nativeInit",                "(Ljava/lang/String;Ljava/lang/String;)I",
                                                                    (void*)android_init},
    {"nativeShutdown",            "()V",                            (void*)android_shutdown},
    {"nativeGetApiLevel",         "()I",                            (void*)android_get_api_level},
    {"nativeGetThermalStatus",    "()I",                            (void*)android_get_thermal_status},
    {"nativeGetBatteryLevel",     "()I",                            (void*)android_get_battery_level},
    {"nativeIsCharging",          "()Z",                            (void*)android_is_charging},
    {"nativeGetDeviceInfo",       "()Ljava/lang/String;",           (void*)android_get_device_info},
    {"nativeConnectDaemon",       "(Ljava/lang/String;II)I",        (void*)android_connect_daemon},
    {"nativeSendDaemonCommand",   "(I[B[B)I",                       (void*)android_send_daemon_command},
    {"nativeStartForegroundService", "(ILjava/lang/String;Ljava/lang/String;Ljava/lang/String;)I",
                                                                    (void*)android_start_foreground_service},
    {"nativeStopForegroundService", "()I",                          (void*)android_stop_foreground_service},
    {"nativeShowNotification",    "(Ljava/lang/String;Ljava/lang/String;I)I",
                                                                    (void*)android_show_notification},
    {"nativeModelDownload",       "(Ljava/lang/String;)I",          (void*)android_model_download},
    {"nativeModelLoad",           "(Ljava/lang/String;)I",          (void*)android_model_load},
    {"nativeModelUnload",         "(Ljava/lang/String;)I",          (void*)android_model_unload},
    {"nativeRunInference",        "(Ljava/lang/String;[B[B)I",      (void*)android_run_inference},
};

jint JNI_OnLoad(JavaVM* vm, void* reserved)
{
    (void)reserved;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "JNI_OnLoad called");

    g_jvm = vm;

    JNIEnv* env;
    if ((*vm)->GetEnv(vm, (void**)&env, JNI_VERSION_1_6) != JNI_OK) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "Failed to get JNI env in JNI_OnLoad");
        return JNI_ERR;
    }

    // Find native class
    jclass temp_class = (*env)->FindClass(env, "com/ainos/AinosNative");
    if (!temp_class) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "Failed to find class com/ainos/AinosNative");
        return JNI_ERR;
    }
    g_ainos_native_class = (*env)->NewGlobalRef(env, temp_class);
    (*env)->DeleteLocalRef(env, temp_class);

    // Register native methods
    jint result = (*env)->RegisterNatives(env, g_ainos_native_class,
                                           g_native_methods,
                                           sizeof(g_native_methods) / sizeof(g_native_methods[0]));
    if (result != JNI_OK) {
        __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                            "Failed to register native methods");
        return JNI_ERR;
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "JNI_OnLoad complete - registered %zu native methods",
                        sizeof(g_native_methods) / sizeof(g_native_methods[0]));

    return JNI_VERSION_1_6;
}

void JNI_OnUnload(JavaVM* vm, void* reserved)
{
    (void)vm;
    (void)reserved;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "JNI_OnUnload called");

    JNIEnv* env;
    if ((*vm)->GetEnv(vm, (void**)&env, JNI_VERSION_1_6) != JNI_OK) {
        return;
    }

    if (g_ainos_native_class) {
        (*env)->UnregisterNatives(env, g_ainos_native_class);
        (*env)->DeleteGlobalRef(env, g_ainos_native_class);
        g_ainos_native_class = NULL;
    }

    ainos_platform_shutdown();
    g_jvm = NULL;
}