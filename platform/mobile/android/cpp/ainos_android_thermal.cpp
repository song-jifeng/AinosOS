/**
 * ainos_android_thermal.cpp
 * Android thermal management implementation
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos_mobile_common.h"
#include <android/log.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <fcntl.h>
#include <dirent.h>
#include <errno.h>

#define LOG_TAG "AinosThermal"

/*============================================================================
 * Thermal Zone Types
 *============================================================================*/

typedef enum {
    THERMAL_ZONE_CPU,
    THERMAL_ZONE_GPU,
    THERMAL_ZONE_BATTERY,
    THERMAL_ZONE_CHARGER,
    THERMAL_ZONE_BOARD,
    THERMAL_ZONE_UNKNOWN
} thermal_zone_type_t;

typedef struct {
    char path[256];
    thermal_zone_type_t type;
    int zone_id;
    float current_temp;
    float throttle_threshold;
    float shutdown_threshold;
    bool available;
} thermal_zone_t;

/*============================================================================
 * Thermal State
 *============================================================================*/

#define MAX_THERMAL_ZONES 32
#define MAX_COOLING_DEVICES 16

typedef struct {
    thermal_zone_t zones[MAX_THERMAL_ZONES];
    int zone_count;
    float max_temp;
    float avg_temp;
    ainos_thermal_status_t current_status;
    ainos_thermal_throttle_t current_throttle;
    int throttle_duration_seconds;
    int shutdown_temp_count;
    pthread_mutex_t lock;
    bool initialized;
} ainos_android_thermal_state_t;

static ainos_android_thermal_state_t g_android_thermal;

/*============================================================================
 * Thermal Zone Discovery
 *============================================================================*/

static thermal_zone_type_t identify_thermal_zone(const char* type_str)
{
    if (!type_str) return THERMAL_ZONE_UNKNOWN;

    if (strstr(type_str, "cpu") || strstr(type_str, "CPU") ||
        strstr(type_str, "cpuss") || strstr(type_str, "core")) {
        return THERMAL_ZONE_CPU;
    }
    if (strstr(type_str, "gpu") || strstr(type_str, "GPU")) {
        return THERMAL_ZONE_GPU;
    }
    if (strstr(type_str, "battery") || strstr(type_str, "Battery") ||
        strstr(type_str, "bms")) {
        return THERMAL_ZONE_BATTERY;
    }
    if (strstr(type_str, "charger") || strstr(type_str, "Charger") ||
        strstr(type_str, "usb")) {
        return THERMAL_ZONE_CHARGER;
    }
    if (strstr(type_str, "board") || strstr(type_str, "Board") ||
        strstr(type_str, "soc") || strstr(type_str, "SoC")) {
        return THERMAL_ZONE_BOARD;
    }
    return THERMAL_ZONE_UNKNOWN;
}

static float get_throttle_threshold(thermal_zone_type_t type)
{
    switch (type) {
        case THERMAL_ZONE_CPU:    return 85.0f;
        case THERMAL_ZONE_GPU:    return 80.0f;
        case THERMAL_ZONE_BATTERY: return 48.0f;
        case THERMAL_ZONE_CHARGER: return 50.0f;
        case THERMAL_ZONE_BOARD:   return 75.0f;
        default:                   return 80.0f;
    }
}

static float get_shutdown_threshold(thermal_zone_type_t type)
{
    switch (type) {
        case THERMAL_ZONE_CPU:    return 100.0f;
        case THERMAL_ZONE_GPU:    return 95.0f;
        case THERMAL_ZONE_BATTERY: return 60.0f;
        case THERMAL_ZONE_CHARGER: return 55.0f;
        case THERMAL_ZONE_BOARD:   return 90.0f;
        default:                   return 95.0f;
    }
}

/*============================================================================
 * Thermal Zone Discovery
 *============================================================================*/

static void discover_thermal_zones(void)
{
    DIR* dir = opendir("/sys/class/thermal");
    if (!dir) {
        __android_log_print(ANDROID_LOG_WARN, LOG_TAG,
                            "Cannot open /sys/class/thermal");
        return;
    }

    struct dirent* entry;
    while ((entry = readdir(dir)) != NULL && g_android_thermal.zone_count < MAX_THERMAL_ZONES) {
        if (strncmp(entry->d_name, "thermal_zone", 12) != 0) {
            continue;
        }

        thermal_zone_t* zone = &g_android_thermal.zones[g_android_thermal.zone_count];
        memset(zone, 0, sizeof(*zone));

        // Read zone type
        char type_path[256];
        snprintf(type_path, sizeof(type_path),
                 "/sys/class/thermal/%s/type", entry->d_name);
        FILE* fp = fopen(type_path, "r");
        if (fp) {
            char type_str[64];
            if (fgets(type_str, sizeof(type_str), fp)) {
                // Remove newline
                size_t len = strlen(type_str);
                if (len > 0 && type_str[len-1] == '\n') type_str[len-1] = '\0';
                zone->type = identify_thermal_zone(type_str);
            }
            fclose(fp);
        }

        // Read zone temperature
        char temp_path[256];
        snprintf(temp_path, sizeof(temp_path),
                 "/sys/class/thermal/%s/temp", entry->d_name);
        fp = fopen(temp_path, "r");
        if (fp) {
            int temp_raw;
            if (fscanf(fp, "%d", &temp_raw) == 1) {
                zone->current_temp = temp_raw / 1000.0f;
                zone->available = true;
            }
            fclose(fp);
        }

        // Extract zone ID
        sscanf(entry->d_name, "thermal_zone%d", &zone->zone_id);
        snprintf(zone->path, sizeof(zone->path), "/sys/class/thermal/%s", entry->d_name);
        zone->throttle_threshold = get_throttle_threshold(zone->type);
        zone->shutdown_threshold = get_shutdown_threshold(zone->type);

        __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG,
                            "Found zone %s: type=%d temp=%.1fC",
                            entry->d_name, zone->type, zone->current_temp);

        g_android_thermal.zone_count++;
    }

    closedir(dir);
}

/*============================================================================
 * Temperature Reading
 *============================================================================*/

static float read_zone_temperature(const thermal_zone_t* zone)
{
    char temp_path[256];
    snprintf(temp_path, sizeof(temp_path), "%s/temp", zone->path);

    FILE* fp = fopen(temp_path, "r");
    if (!fp) return -1.0f;

    int temp_raw;
    float temp = -1.0f;
    if (fscanf(fp, "%d", &temp_raw) == 1) {
        temp = temp_raw / 1000.0f;
    }
    fclose(fp);
    return temp;
}

static float read_battery_temperature_sysfs(void)
{
    const char* paths[] = {
        "/sys/class/power_supply/battery/temp",
        "/sys/class/power_supply/Battery/temp",
        "/sys/devices/platform/battery/temp",
        NULL
    };

    for (int i = 0; paths[i]; i++) {
        FILE* fp = fopen(paths[i], "r");
        if (fp) {
            int temp_raw;
            if (fscanf(fp, "%d", &temp_raw) == 1) {
                fclose(fp);
                return temp_raw / 10.0f;
            }
            fclose(fp);
        }
    }
    return -1.0f;
}

/*============================================================================
 * Thermal Status Computation
 *============================================================================*/

static ainos_thermal_status_t compute_thermal_status(float max_temp)
{
    if (max_temp >= 85.0f) return AINOS_THERMAL_STATUS_EMERGENCY;
    if (max_temp >= 75.0f) return AINOS_THERMAL_STATUS_CRITICAL;
    if (max_temp >= 65.0f) return AINOS_THERMAL_STATUS_HOT;
    if (max_temp >= 55.0f) return AINOS_THERMAL_STATUS_WARM;
    return AINOS_THERMAL_STATUS_NORMAL;
}

static ainos_thermal_throttle_t compute_throttle_level(float max_temp)
{
    if (max_temp >= 85.0f) return AINOS_THERMAL_THROTTLE_SHUTDOWN;
    if (max_temp >= 75.0f) return AINOS_THERMAL_THROTTLE_SEVERE;
    if (max_temp >= 65.0f) return AINOS_THERMAL_THROTTLE_MODERATE;
    if (max_temp >= 55.0f) return AINOS_THERMAL_THROTTLE_MILD;
    return AINOS_THERMAL_THROTTLE_NONE;
}

/*============================================================================
 * Public API Implementation
 *============================================================================*/

void ainos_android_thermal_init(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);

    if (g_android_thermal.initialized) {
        pthread_mutex_unlock(&g_android_thermal.lock);
        return;
    }

    memset(&g_android_thermal, 0, sizeof(g_android_thermal));
    g_android_thermal.current_status = AINOS_THERMAL_STATUS_NORMAL;
    g_android_thermal.current_throttle = AINOS_THERMAL_THROTTLE_NONE;
    g_android_thermal.max_temp = 35.0f;
    g_android_thermal.avg_temp = 35.0f;

    // Initialize mutex
    pthread_mutex_init(&g_android_thermal.lock, NULL);

    // Discover thermal zones
    discover_thermal_zones();

    g_android_thermal.initialized = true;
    pthread_mutex_unlock(&g_android_thermal.lock);

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Thermal initialized: %d zones found",
                        g_android_thermal.zone_count);
}

void ainos_android_thermal_shutdown(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);
    g_android_thermal.initialized = false;
    g_android_thermal.zone_count = 0;
    pthread_mutex_unlock(&g_android_thermal.lock);
    pthread_mutex_destroy(&g_android_thermal.lock);
}

ainos_status_t ainos_android_thermal_update(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);

    if (!g_android_thermal.initialized) {
        pthread_mutex_unlock(&g_android_thermal.lock);
        return AINOS_ERROR_NOT_INITIALIZED;
    }

    float max_temp = 0.0f;
    float temp_sum = 0.0f;
    int temp_count = 0;

    // Update all thermal zones
    for (int i = 0; i < g_android_thermal.zone_count; i++) {
        thermal_zone_t* zone = &g_android_thermal.zones[i];
        float temp = read_zone_temperature(zone);
        if (temp >= 0.0f) {
            zone->current_temp = temp;
            if (temp > max_temp) max_temp = temp;
            temp_sum += temp;
            temp_count++;
        }
    }

    // Also check battery temperature
    float batt_temp = read_battery_temperature_sysfs();
    if (batt_temp > 0.0f) {
        if (batt_temp > max_temp) max_temp = batt_temp;
        temp_sum += batt_temp;
        temp_count++;
    }

    g_android_thermal.max_temp = max_temp;
    if (temp_count > 0) {
        g_android_thermal.avg_temp = temp_sum / temp_count;
    }

    // Update status
    ainos_thermal_status_t old_status = g_android_thermal.current_status;
    g_android_thermal.current_status = compute_thermal_status(max_temp);
    g_android_thermal.current_throttle = compute_throttle_level(max_temp);

    // Track throttle duration
    if (g_android_thermal.current_throttle > AINOS_THERMAL_THROTTLE_NONE) {
        g_android_thermal.throttle_duration_seconds += 5;
    } else {
        g_android_thermal.throttle_duration_seconds = 0;
    }

    // Track shutdown temperature count
    if (max_temp >= 85.0f) {
        g_android_thermal.shutdown_temp_count++;
    } else {
        g_android_thermal.shutdown_temp_count = 0;
    }

    pthread_mutex_unlock(&g_android_thermal.lock);

    // Log if status changed
    if (old_status != g_android_thermal.current_status) {
        __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                            "Thermal status changed: %d -> %d (max=%.1fC, avg=%.1fC)",
                            old_status, g_android_thermal.current_status,
                            max_temp, g_android_thermal.avg_temp);
    }

    return AINOS_OK;
}

ainos_status_t ainos_android_thermal_get_status(ainos_thermal_status_t* status)
{
    if (!status) return AINOS_ERROR_INVALID_PARAM;

    pthread_mutex_lock(&g_android_thermal.lock);
    *status = g_android_thermal.current_status;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return AINOS_OK;
}

ainos_status_t ainos_android_thermal_get_throttle(ainos_thermal_throttle_t* throttle)
{
    if (!throttle) return AINOS_ERROR_INVALID_PARAM;

    pthread_mutex_lock(&g_android_thermal.lock);
    *throttle = g_android_thermal.current_throttle;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return AINOS_OK;
}

ainos_status_t ainos_android_thermal_get_max_temp(float* temp)
{
    if (!temp) return AINOS_ERROR_INVALID_PARAM;

    pthread_mutex_lock(&g_android_thermal.lock);
    *temp = g_android_thermal.max_temp;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return AINOS_OK;
}

ainos_status_t ainos_android_thermal_get_avg_temp(float* temp)
{
    if (!temp) return AINOS_ERROR_INVALID_PARAM;

    pthread_mutex_lock(&g_android_thermal.lock);
    *temp = g_android_thermal.avg_temp;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return AINOS_OK;
}

bool ainos_android_thermal_is_critical(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);
    bool critical = (g_android_thermal.current_status >= AINOS_THERMAL_STATUS_CRITICAL);
    pthread_mutex_unlock(&g_android_thermal.lock);
    return critical;
}

int ainos_android_thermal_get_zone_count(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);
    int count = g_android_thermal.zone_count;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return count;
}

int ainos_android_thermal_get_throttle_duration(void)
{
    pthread_mutex_lock(&g_android_thermal.lock);
    int duration = g_android_thermal.throttle_duration_seconds;
    pthread_mutex_unlock(&g_android_thermal.lock);
    return duration;
}

/*============================================================================
 * CPU Frequency Scaling
 *============================================================================*/

typedef struct {
    int cpu_id;
    int max_freq;
    int min_freq;
    int cur_freq;
    char governor[32];
    bool online;
} cpu_info_t;

#define MAX_CPUS 16

static cpu_info_t g_cpu_info[MAX_CPUS];
static int g_cpu_count = 0;

void ainos_android_thermal_discover_cpus(void)
{
    g_cpu_count = 0;
    for (int i = 0; i < MAX_CPUS; i++) {
        char path[256];
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_max_freq", i);

        if (access(path, F_OK) != 0) {
            continue;
        }

        cpu_info_t* cpu = &g_cpu_info[g_cpu_count];
        memset(cpu, 0, sizeof(*cpu));
        cpu->cpu_id = i;
        cpu->online = true;

        // Read max frequency
        FILE* fp = fopen(path, "r");
        if (fp) {
            fscanf(fp, "%d", &cpu->max_freq);
            fclose(fp);
        }

        // Read min frequency
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/cpuinfo_min_freq", i);
        fp = fopen(path, "r");
        if (fp) {
            fscanf(fp, "%d", &cpu->min_freq);
            fclose(fp);
        }

        // Read current frequency
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq", i);
        fp = fopen(path, "r");
        if (fp) {
            fscanf(fp, "%d", &cpu->cur_freq);
            fclose(fp);
        }

        // Read governor
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_governor", i);
        fp = fopen(path, "r");
        if (fp) {
            if (fgets(cpu->governor, sizeof(cpu->governor), fp)) {
                size_t len = strlen(cpu->governor);
                if (len > 0 && cpu->governor[len-1] == '\n') cpu->governor[len-1] = '\0';
            }
            fclose(fp);
        }

        g_cpu_count++;
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Discovered %d CPUs", g_cpu_count);
}

void ainos_android_thermal_set_cpu_governor(const char* governor)
{
    for (int i = 0; i < g_cpu_count; i++) {
        char path[256];
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_governor",
                 g_cpu_info[i].cpu_id);

        FILE* fp = fopen(path, "w");
        if (fp) {
            if (fprintf(fp, "%s", governor) > 0) {
                __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                    "CPU%d governor set to %s", i, governor);
            }
            fclose(fp);
        }
    }
}

void ainos_android_thermal_limit_cpu_freq(int max_freq_khz)
{
    for (int i = 0; i < g_cpu_count; i++) {
        char path[256];
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_max_freq",
                 g_cpu_info[i].cpu_id);

        FILE* fp = fopen(path, "w");
        if (fp) {
            if (fprintf(fp, "%d", max_freq_khz) > 0) {
                __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                    "CPU%d max freq limited to %d kHz",
                                    i, max_freq_khz);
            }
            fclose(fp);
        }
    }
}

void ainos_android_thermal_restore_cpu_freq(void)
{
    for (int i = 0; i < g_cpu_count; i++) {
        char path[256];
        snprintf(path, sizeof(path),
                 "/sys/devices/system/cpu/cpu%d/cpufreq/scaling_max_freq",
                 g_cpu_info[i].cpu_id);

        FILE* fp = fopen(path, "w");
        if (fp) {
            if (fprintf(fp, "%d", g_cpu_info[i].max_freq) > 0) {
                __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                                    "CPU%d max freq restored to %d kHz",
                                    i, g_cpu_info[i].max_freq);
            }
            fclose(fp);
        }
    }
}

/*============================================================================
 * Thermal Policy Application
 *============================================================================*/

void ainos_android_thermal_apply_policy(ainos_thermal_status_t status)
{
    switch (status) {
        case AINOS_THERMAL_STATUS_NORMAL:
            ainos_android_thermal_restore_cpu_freq();
            ainos_android_thermal_set_cpu_governor("schedutil");
            break;

        case AINOS_THERMAL_STATUS_WARM:
            ainos_android_thermal_set_cpu_governor("conservative");
            break;

        case AINOS_THERMAL_STATUS_HOT:
            ainos_android_thermal_limit_cpu_freq(1500000); // 1.5 GHz
            ainos_android_thermal_set_cpu_governor("powersave");
            break;

        case AINOS_THERMAL_STATUS_CRITICAL:
            ainos_android_thermal_limit_cpu_freq(1000000); // 1.0 GHz
            ainos_android_thermal_set_cpu_governor("powersave");
            break;

        case AINOS_THERMAL_STATUS_EMERGENCY:
            ainos_android_thermal_limit_cpu_freq(500000);  // 500 MHz
            ainos_android_thermal_set_cpu_governor("powersave");
            break;

        default:
            break;
    }

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "Thermal policy applied for status %d", status);
}