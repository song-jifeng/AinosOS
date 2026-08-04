// Ainos OS - macOS Thermal Monitoring Implementation
// ============================================================================
//
// This file implements thermal monitoring for AinosOS on macOS using
// IOKit, AppleSMC (System Management Controller), and the IORegistry.
//
// Temperature Sources:
//   - Apple Silicon (M1/M2/M3): IORegistry "thermal-zones" node
//   - Intel:                   AppleSMC keys (TC0p, TC0P, etc.) or IORegistry
//   - Fallback:                sysctl hw.* thermal values
//
// Power Source Monitoring:
//   - IOKit IOPowerSource service for battery/AC detection
//   - IOPSCopyPowerSourcesInfo for detailed battery state
//
// Integration:
//   - Thermal state is written to a shared file for the Rust daemon
//   - Notifications via dispatch_source for thermal state changes
//   - Callback for power policy system integration
//
// Compile with:
//   clang -x objective-c -fobjc-arc -framework Foundation \
//         -framework IOKit -framework CoreFoundation \
//         -o ainos_thermal.dylib -dynamiclib ainos_thermal.c
//
// Link with:
//   -framework Foundation -framework IOKit -framework CoreFoundation

#include "ainos_thermal.h"
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOTypes.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/ps/IOPSKeys.h>
#include <IOKit/ps/IOPowerSources.h>
#include <IOKit/pwr_mgt/IOPMLib.h>
#include <IOKit/IOBSD.h>
#include <dispatch/dispatch.h>
#include <os/log.h>
#include <os/signpost.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <time.h>
#include <sys/param.h>
#include <sys/sysctl.h>
#include <mach/mach_time.h>

// ============================================================================
// Constants
// ============================================================================

#define AINOS_THERMAL_DEFAULT_INTERVAL_MS  2000
#define AINOS_THERMAL_MIN_INTERVAL_MS      500
#define AINOS_THERMAL_MAX_INTERVAL_MS      10000
#define AINOS_THERMAL_POLICY_FILE          "/var/run/ainos/thermal_policy"
#define AINOS_THERMAL_SMC_PATH             "AppleSMC"
#define AINOS_THERMAL_IOREG_CPU_TEMP       "cpu_die"
#define AINOS_THERMAL_IOREG_GPU_TEMP       "gpu_die"
#define AINOS_THERMAL_MAX_SENSORS          16

// SMC data structure (matches Apple's SMC protocol)
typedef struct {
    uint32_t    key;
    uint8_t     data_type;
    uint8_t     data_size;
    uint8_t     data[32];
} ainos_smc_data_t;

// IOKit connection for SMC
typedef struct {
    io_connect_t connect;
    io_service_t service;
    bool         available;
} ainos_smc_connection_t;

// ============================================================================
// Thermal Monitor Structure
// ============================================================================

struct ainos_thermal_monitor_s {
    // Configuration
    double      threshold_cool_warm;
    double      threshold_warm_hot;
    double      threshold_hot_critical;
    uint32_t    interval_ms;

    // State
    ainos_thermal_snapshot_t    current_snapshot;
    ainos_thermal_zone_t        last_zone;
    ainos_power_mode_t          last_mode;
    pthread_mutex_t             snapshot_lock;

    // IOKit connections
    ainos_smc_connection_t      smc;
    io_iterator_t               power_source_iterator;
    io_service_t                power_source_service;
    IONotificationPortRef       power_notification_port;
    CFRunLoopSourceRef          power_runloop_source;

    // Dispatch
    dispatch_queue_t            queue;
    dispatch_source_t           timer_source;
    dispatch_source_t           thermal_notification_source;
    bool                        running;

    // Callback
    ainos_thermal_callback_t    callback;
    void                       *callback_context;

    // Logging
    os_log_t                    log;

    // Policy file
    int                         policy_fd;
};

// ============================================================================
// Forward Declarations
// ============================================================================

static void ainos_thermal_monitor_tick(void *context);
static void ainos_thermal_monitor_read_sensors(ainos_thermal_monitor_t monitor);
static void ainos_thermal_monitor_read_power_source(ainos_thermal_monitor_t monitor);
static void ainos_thermal_monitor_update_policy(ainos_thermal_monitor_t monitor);
static void ainos_thermal_monitor_fire_callback(ainos_thermal_monitor_t monitor,
                                                ainos_thermal_zone_t old_zone);
static bool ainos_thermal_smc_open(ainos_thermal_monitor_t monitor);
static void ainos_thermal_smc_close(ainos_thermal_monitor_t monitor);
static bool ainos_thermal_smc_call(ainos_smc_connection_t *smc,
                                   uint32_t selector,
                                   ainos_smc_data_t *data);
static void ainos_thermal_power_source_changed(void *context, io_iterator_t iterator);

// ============================================================================
// Create / Destroy
// ============================================================================

ainos_thermal_monitor_t ainos_thermal_monitor_create(void) {
    return ainos_thermal_monitor_create_with_interval(AINOS_THERMAL_DEFAULT_INTERVAL_MS);
}

ainos_thermal_monitor_t ainos_thermal_monitor_create_with_interval(uint32_t interval_ms) {
    ainos_thermal_monitor_t monitor = (ainos_thermal_monitor_t)
        calloc(1, sizeof(struct ainos_thermal_monitor_s));
    if (!monitor) return NULL;

    // Initialize configuration
    monitor->threshold_cool_warm = AINOS_THERMAL_THRESHOLD_COOL_WARM;
    monitor->threshold_warm_hot  = AINOS_THERMAL_THRESHOLD_WARM_HOT;
    monitor->threshold_hot_critical = AINOS_THERMAL_THRESHOLD_HOT_CRITICAL;

    if (interval_ms < AINOS_THERMAL_MIN_INTERVAL_MS)
        interval_ms = AINOS_THERMAL_MIN_INTERVAL_MS;
    if (interval_ms > AINOS_THERMAL_MAX_INTERVAL_MS)
        interval_ms = AINOS_THERMAL_MAX_INTERVAL_MS;
    monitor->interval_ms = interval_ms;

    // Initialize snapshot
    monitor->current_snapshot.cpu_temp_celsius = 40.0;
    monitor->current_snapshot.gpu_temp_celsius = 0.0;
    monitor->current_snapshot.ambient_temp_celsius = 0.0;
    monitor->current_snapshot.zone = AINOS_THERMAL_ZONE_COOL;
    monitor->current_snapshot.power_mode = AINOS_POWER_MODE_MAX;
    monitor->current_snapshot.recommended_threads = 4;
    monitor->current_snapshot.sensor_available = false;
    monitor->current_snapshot.throttle_active = false;
    monitor->current_snapshot.power_source = AINOS_POWER_SOURCE_UNKNOWN;
    monitor->current_snapshot.battery_percentage = -1.0;
    monitor->current_snapshot.battery_cycle_count = -1;
    monitor->current_snapshot.timestamp_ns = 0;

    monitor->last_zone = AINOS_THERMAL_ZONE_COOL;
    monitor->last_mode = AINOS_POWER_MODE_MAX;

    // Initialize locks
    pthread_mutex_init(&monitor->snapshot_lock, NULL);

    // Set up dispatch queue
    monitor->queue = dispatch_queue_create(
        "com.ainos.thermal", DISPATCH_QUEUE_SERIAL);

    // Initialize logging
    monitor->log = os_log_create(AINOS_LOG_SUBSYSTEM, "thermal");

    // Initialize SMC
    monitor->smc.connect = 0;
    monitor->smc.service = 0;
    monitor->smc.available = false;

    // Initialize power source
    monitor->power_source_iterator = 0;
    monitor->power_source_service = 0;
    monitor->power_notification_port = NULL;
    monitor->power_runloop_source = NULL;

    // Policy file
    monitor->policy_fd = -1;

    // Try to open SMC
    ainos_thermal_smc_open(monitor);

    // Try to read initial sensor values
    ainos_thermal_monitor_read_sensors(monitor);
    ainos_thermal_monitor_read_power_source(monitor);

    os_log_info(monitor->log, "Thermal monitor created (interval=%ums)",
                monitor->interval_ms);

    return monitor;
}

void ainos_thermal_monitor_destroy(ainos_thermal_monitor_t monitor) {
    if (!monitor) return;

    os_log_info(monitor->log, "Thermal monitor destroying");

    // Stop monitoring
    if (monitor->running) {
        ainos_thermal_monitor_stop(monitor);
    }

    // Close SMC
    ainos_thermal_smc_close(monitor);

    // Clean up power source notification
    if (monitor->power_notification_port) {
        IONotificationPortDestroy(monitor->power_notification_port);
    }
    if (monitor->power_source_iterator) {
        IOObjectRelease(monitor->power_source_iterator);
    }
    if (monitor->power_source_service) {
        IOObjectRelease(monitor->power_source_service);
    }

    // Close policy file
    if (monitor->policy_fd >= 0) {
        close(monitor->policy_fd);
    }

    // Release dispatch objects
    if (monitor->queue) {
        dispatch_release(monitor->queue);
    }

    // Release logging
    if (monitor->log) {
        os_release(monitor->log);
    }

    pthread_mutex_destroy(&monitor->snapshot_lock);

    free(monitor);
}

// ============================================================================
// Configuration
// ============================================================================

void ainos_thermal_monitor_set_thresholds(ainos_thermal_monitor_t monitor,
                                          double cool_warm,
                                          double warm_hot,
                                          double hot_critical) {
    if (!monitor) return;

    if (cool_warm > 0)   monitor->threshold_cool_warm = cool_warm;
    if (warm_hot > 0)    monitor->threshold_warm_hot = warm_hot;
    if (hot_critical > 0) monitor->threshold_hot_critical = hot_critical;

    os_log_info(monitor->log, "Thermal thresholds set: %.1f/%.1f/%.1f",
                monitor->threshold_cool_warm,
                monitor->threshold_warm_hot,
                monitor->threshold_hot_critical);
}

void ainos_thermal_monitor_set_interval(ainos_thermal_monitor_t monitor,
                                        uint32_t interval_ms) {
    if (!monitor) return;

    if (interval_ms < AINOS_THERMAL_MIN_INTERVAL_MS)
        interval_ms = AINOS_THERMAL_MIN_INTERVAL_MS;
    if (interval_ms > AINOS_THERMAL_MAX_INTERVAL_MS)
        interval_ms = AINOS_THERMAL_MAX_INTERVAL_MS;

    monitor->interval_ms = interval_ms;

    // If running, restart the timer with the new interval
    if (monitor->running && monitor->timer_source) {
        dispatch_source_set_timer(monitor->timer_source,
            dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * interval_ms),
            NSEC_PER_MSEC * interval_ms, 0);
    }

    os_log_info(monitor->log, "Polling interval set to %ums", interval_ms);
}

void ainos_thermal_monitor_set_callback(ainos_thermal_monitor_t monitor,
                                        ainos_thermal_callback_t callback,
                                        void *context) {
    if (!monitor) return;
    monitor->callback = callback;
    monitor->callback_context = context;
}

// ============================================================================
// Monitoring Control
// ============================================================================

bool ainos_thermal_monitor_start(ainos_thermal_monitor_t monitor) {
    if (!monitor || monitor->running) return false;

    // Create the timer dispatch source
    monitor->timer_source = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_TIMER, 0, 0, monitor->queue);

    if (!monitor->timer_source) {
        os_log_error(monitor->log, "Failed to create timer dispatch source");
        return false;
    }

    dispatch_source_set_timer(monitor->timer_source,
        dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_MSEC * monitor->interval_ms),
        NSEC_PER_MSEC * monitor->interval_ms, 0);

    dispatch_source_set_event_handler(monitor->timer_source, ^{
        ainos_thermal_monitor_tick((void *)monitor);
    });

    // Set up power source change notification
    monitor->power_notification_port = IONotificationPortCreate(kIOMasterPortDefault);
    if (monitor->power_notification_port) {
        monitor->power_runloop_source = IONotificationPortGetRunLoopSource(
            monitor->power_notification_port);
        if (monitor->power_runloop_source) {
            CFRunLoopAddSource(CFRunLoopGetMain(),
                               monitor->power_runloop_source,
                               kCFRunLoopDefaultMode);
        }

        // Register for power source changes
        IOServiceAddMatchingNotification(
            monitor->power_notification_port,
            kIOPublishNotification,
            IOServiceMatching("IOPowerSource"),
            ainos_thermal_power_source_changed,
            monitor,
            &monitor->power_source_iterator);

        // Handle initial notification
        ainos_thermal_power_source_changed(monitor, monitor->power_source_iterator);
    }

    // Set up thermal notification source
    monitor->thermal_notification_source = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_DATA_ADD, 0, 0, monitor->queue);
    if (monitor->thermal_notification_source) {
        dispatch_source_set_event_handler(monitor->thermal_notification_source, ^{
            // Thermal notification received, read sensors immediately
            ainos_thermal_monitor_read_sensors(monitor);
            ainos_thermal_monitor_update_policy(monitor);
        });
        dispatch_resume(monitor->thermal_notification_source);
    }

    // Resume the timer
    monitor->running = true;
    dispatch_resume(monitor->timer_source);

    os_log_info(monitor->log, "Thermal monitoring started (interval=%ums)",
                monitor->interval_ms);

    return true;
}

void ainos_thermal_monitor_stop(ainos_thermal_monitor_t monitor) {
    if (!monitor || !monitor->running) return;

    monitor->running = false;

    // Cancel timer
    if (monitor->timer_source) {
        dispatch_source_cancel(monitor->timer_source);
        dispatch_release(monitor->timer_source);
        monitor->timer_source = NULL;
    }

    // Cancel notification source
    if (monitor->thermal_notification_source) {
        dispatch_source_cancel(monitor->thermal_notification_source);
        dispatch_release(monitor->thermal_notification_source);
        monitor->thermal_notification_source = NULL;
    }

    // Remove runloop source
    if (monitor->power_runloop_source && monitor->power_notification_port) {
        CFRunLoopRemoveSource(CFRunLoopGetMain(),
                              monitor->power_runloop_source,
                              kCFRunLoopDefaultMode);
    }

    os_log_info(monitor->log, "Thermal monitoring stopped");
}

// ============================================================================
// Timer Tick
// ============================================================================

static void ainos_thermal_monitor_tick(void *context) {
    ainos_thermal_monitor_t monitor = (ainos_thermal_monitor_t)context;
    if (!monitor) return;

    os_signpost_id_t spid = os_signpost_id_make_with_pointer(monitor->log, monitor);
    os_signpost_interval_begin(monitor->log, spid, "ThermalTick");

    // Read sensors
    ainos_thermal_monitor_read_sensors(monitor);
    ainos_thermal_monitor_read_power_source(monitor);

    // Update policy file
    ainos_thermal_monitor_update_policy(monitor);

    os_signpost_interval_end(monitor->log, spid, "ThermalTick");
}

// ============================================================================
// Sensor Reading
// ============================================================================

static void ainos_thermal_monitor_read_sensors(ainos_thermal_monitor_t monitor) {
    if (!monitor) return;

    double cpu_temp = -1.0;
    double gpu_temp = -1.0;
    double ambient_temp = -1.0;

    // Try AppleSMC first (Intel Macs)
    if (monitor->smc.available) {
        cpu_temp = ainos_thermal_smc_read_temperature("TC0p");
        if (cpu_temp < 0) cpu_temp = ainos_thermal_smc_read_temperature("TC0P");
        if (cpu_temp < 0) cpu_temp = ainos_thermal_smc_read_temperature("TC0D");

        gpu_temp = ainos_thermal_smc_read_temperature("TG0p");
        if (gpu_temp < 0) gpu_temp = ainos_thermal_smc_read_temperature("TG0D");

        ambient_temp = ainos_thermal_smc_read_temperature("TA0p");
    }

    // If SMC didn't work, try IORegistry (Apple Silicon Macs)
    if (cpu_temp < 0) {
        cpu_temp = ainos_thermal_ioregistry_get_cpu_temperature();
    }
    if (gpu_temp < 0) {
        gpu_temp = ainos_thermal_ioregistry_get_gpu_temperature();
    }

    // If still no temperature, try sysctl
    if (cpu_temp < 0) {
        cpu_temp = ainos_thermal_ioregistry_get_cpu_temperature();
    }

    // Fallback: use thermal pressure level as proxy
    if (cpu_temp < 0) {
        int pressure = ainos_thermal_get_system_thermal_pressure();
        switch (pressure) {
            case 0: cpu_temp = 40.0; break;
            case 1: cpu_temp = 75.0; break;
            case 2: cpu_temp = 88.0; break;
            case 3: cpu_temp = 96.0; break;
            default: cpu_temp = 50.0; break;
        }
    }

    // Determine thermal zone and power mode
    ainos_thermal_zone_t zone = ainos_thermal_celsius_to_zone(cpu_temp);
    ainos_power_mode_t mode = ainos_thermal_zone_to_power_mode(zone);
    int threads = ainos_thermal_power_mode_to_threads(mode);
    bool throttle = (mode >= AINOS_POWER_MODE_EFFICIENT);

    // Update snapshot atomically
    pthread_mutex_lock(&monitor->snapshot_lock);

    ainos_thermal_zone_t old_zone = monitor->current_snapshot.zone;
    ainos_power_mode_t old_mode = monitor->current_snapshot.power_mode;

    monitor->current_snapshot.cpu_temp_celsius = cpu_temp;
    monitor->current_snapshot.gpu_temp_celsius = gpu_temp;
    monitor->current_snapshot.ambient_temp_celsius = ambient_temp;
    monitor->current_snapshot.zone = zone;
    monitor->current_snapshot.power_mode = mode;
    monitor->current_snapshot.recommended_threads = threads;
    monitor->current_snapshot.sensor_available = (cpu_temp > 0);
    monitor->current_snapshot.throttle_active = throttle;
    monitor->current_snapshot.timestamp_ns =
        clock_gettime_nsec_np(CLOCK_UPTIME_RAW);

    pthread_mutex_unlock(&monitor->snapshot_lock);

    // Log if zone or mode changed
    if (old_zone != zone || old_mode != mode) {
        os_log_info(monitor->log,
            "Thermal state: temp=%.1f°C, zone=%s, mode=%s, threads=%d",
            cpu_temp,
            ainos_thermal_zone_name(zone),
            ainos_thermal_power_mode_name(mode),
            threads);

        // Fire callback
        if (old_zone != zone) {
            ainos_thermal_monitor_fire_callback(monitor, old_zone);
        }
    }

    os_log_debug(monitor->log, "Sensor read: CPU=%.1f°C, GPU=%.1f°C, ambient=%.1f°C",
                 cpu_temp, gpu_temp, ambient_temp);
}

// ============================================================================
// Power Source Monitoring
// ============================================================================

static void ainos_thermal_monitor_read_power_source(ainos_thermal_monitor_t monitor) {
    if (!monitor) return;

    ainos_power_source_t source = AINOS_POWER_SOURCE_UNKNOWN;
    double battery_pct = -1.0;
    int cycle_count = -1;

    // Use IOKit power source API
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (power_info) {
        CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
        if (sources) {
            CFIndex count = CFArrayGetCount(sources);
            if (count > 0) {
                CFDictionaryRef source_info = IOPSGetPowerSourceDescription(power_info,
                    CFArrayGetValueAtIndex(sources, 0));
                if (source_info) {
                    // Check power source state
                    CFStringRef state = CFDictionaryGetValue(source_info,
                        CFSTR(kIOPSPowerSourceStateKey));
                    if (state) {
                        if (CFStringCompare(state, CFSTR(kIOPSACPowerValue), 0) == kCFCompareEqualTo) {
                            source = AINOS_POWER_SOURCE_AC;
                        } else if (CFStringCompare(state, CFSTR(kIOPSBatteryPowerValue), 0) == kCFCompareEqualTo) {
                            source = AINOS_POWER_SOURCE_BATTERY;
                        }
                    }

                    // Check battery percentage
                    CFNumberRef capacity = CFDictionaryGetValue(source_info,
                        CFSTR(kIOPSCurrentCapacityKey));
                    CFNumberRef max_capacity = CFDictionaryGetValue(source_info,
                        CFSTR(kIOPSMaxCapacityKey));
                    if (capacity && max_capacity) {
                        int cur = 0, max = 0;
                        CFNumberGetValue(capacity, kCFNumberIntType, &cur);
                        CFNumberGetValue(max_capacity, kCFNumberIntType, &max);
                        if (max > 0) {
                            battery_pct = (double)cur / (double)max * 100.0;
                        }
                    }

                    // Check cycle count
                    CFNumberRef cycles = CFDictionaryGetValue(source_info,
                        CFSTR(kIOPSBatteryCycleCountKey));
                    if (cycles) {
                        CFNumberGetValue(cycles, kCFNumberIntType, &cycle_count);
                    }
                }
            }
            CFRelease(sources);
        }
        CFRelease(power_info);
    }

    // Fallback: use IOPMGetPowerSource
    if (source == AINOS_POWER_SOURCE_UNKNOWN) {
        CFStringRef power_source = IOPMGetPowerSource();
        if (power_source) {
            if (CFStringCompare(power_source, CFSTR(kIOPMInternalBattery), 0) == kCFCompareEqualTo) {
                source = AINOS_POWER_SOURCE_BATTERY;
            } else if (CFStringCompare(power_source, CFSTR(kIOPMACPower), 0) == kCFCompareEqualTo) {
                source = AINOS_POWER_SOURCE_AC;
            }
            CFRelease(power_source);
        }
    }

    pthread_mutex_lock(&monitor->snapshot_lock);
    monitor->current_snapshot.power_source = source;
    monitor->current_snapshot.battery_percentage = battery_pct;
    monitor->current_snapshot.battery_cycle_count = cycle_count;
    pthread_mutex_unlock(&monitor->snapshot_lock);
}

static void ainos_thermal_power_source_changed(void *context, io_iterator_t iterator) {
    ainos_thermal_monitor_t monitor = (ainos_thermal_monitor_t)context;
    if (!monitor) return;

    // Drain the iterator
    io_service_t service;
    while ((service = IOIteratorNext(iterator)) != 0) {
        IOObjectRelease(service);
    }

    // Read the updated power source state
    ainos_thermal_monitor_read_power_source(monitor);

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_power_source_t source = monitor->current_snapshot.power_source;
    double battery = monitor->current_snapshot.battery_percentage;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    os_log_info(monitor->log, "Power source changed: %s (battery=%.1f%%)",
                ainos_thermal_power_source_name(source), battery);
}

// ============================================================================
// Policy File Update
// ============================================================================

static void ainos_thermal_monitor_update_policy(ainos_thermal_monitor_t monitor) {
    if (!monitor) return;

    // Write the current thermal state to a shared file for the Rust daemon
    // to read. The file format is a simple JSON line:
    //   {"cpu_temp":45.2,"zone":"COOL","mode":"MAX","threads":4,"power_source":"AC","battery_pct":-1}
    //
    // This is the same format used by the Rust daemon's thermal module.

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_thermal_snapshot_t snap = monitor->current_snapshot;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    // Ensure the directory exists
    static bool dir_created = false;
    if (!dir_created) {
        mkdir("/var/run/ainos", 0755);
        dir_created = true;
    }

    // Open the policy file (create if not exists)
    int fd = open(AINOS_THERMAL_POLICY_FILE,
                  O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        os_log_debug(monitor->log, "Failed to open policy file: %{darwin.errno}d", errno);
        return;
    }

    char buffer[512];
    int len = snprintf(buffer, sizeof(buffer),
        "{\"cpu_temp\":%.1f,\"gpu_temp\":%.1f,\"zone\":\"%s\","
        "\"mode\":\"%s\",\"threads\":%d,\"sensor_available\":%s,"
        "\"throttle_active\":%s,\"power_source\":\"%s\","
        "\"battery_pct\":%.1f,\"battery_cycles\":%d}\n",
        snap.cpu_temp_celsius,
        snap.gpu_temp_celsius,
        ainos_thermal_zone_name(snap.zone),
        ainos_thermal_power_mode_name(snap.power_mode),
        snap.recommended_threads,
        snap.sensor_available ? "true" : "false",
        snap.throttle_active ? "true" : "false",
        ainos_thermal_power_source_name(snap.power_source),
        snap.battery_percentage,
        snap.battery_cycle_count);

    ssize_t written = write(fd, buffer, (size_t)len);
    if (written < 0) {
        os_log_debug(monitor->log, "Failed to write policy file: %{darwin.errno}d", errno);
    }

    close(fd);
}

// ============================================================================
// Callback
// ============================================================================

static void ainos_thermal_monitor_fire_callback(ainos_thermal_monitor_t monitor,
                                                ainos_thermal_zone_t old_zone) {
    if (!monitor || !monitor->callback) return;

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_thermal_snapshot_t snap = monitor->current_snapshot;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    monitor->callback(monitor->callback_context, &snap, old_zone);
}

// ============================================================================
// Query Functions
// ============================================================================

bool ainos_thermal_monitor_get_snapshot(ainos_thermal_monitor_t monitor,
                                        ainos_thermal_snapshot_t *snapshot_out) {
    if (!monitor || !snapshot_out) return false;

    pthread_mutex_lock(&monitor->snapshot_lock);
    *snapshot_out = monitor->current_snapshot;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return true;
}

bool ainos_thermal_monitor_read_now(ainos_thermal_monitor_t monitor,
                                    ainos_thermal_snapshot_t *snapshot_out) {
    if (!monitor) return false;

    // Force an immediate sensor read
    ainos_thermal_monitor_read_sensors(monitor);
    ainos_thermal_monitor_read_power_source(monitor);

    if (snapshot_out) {
        pthread_mutex_lock(&monitor->snapshot_lock);
        *snapshot_out = monitor->current_snapshot;
        pthread_mutex_unlock(&monitor->snapshot_lock);
    }

    return true;
}

ainos_thermal_zone_t ainos_thermal_monitor_get_zone(ainos_thermal_monitor_t monitor) {
    if (!monitor) return AINOS_THERMAL_ZONE_COOL;

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_thermal_zone_t zone = monitor->current_snapshot.zone;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return zone;
}

ainos_power_mode_t ainos_thermal_monitor_get_power_mode(ainos_thermal_monitor_t monitor) {
    if (!monitor) return AINOS_POWER_MODE_MAX;

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_power_mode_t mode = monitor->current_snapshot.power_mode;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return mode;
}

int ainos_thermal_monitor_get_recommended_threads(ainos_thermal_monitor_t monitor) {
    if (!monitor) return 4;

    pthread_mutex_lock(&monitor->snapshot_lock);
    int threads = monitor->current_snapshot.recommended_threads;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return threads;
}

// ============================================================================
// Power Source Queries
// ============================================================================

ainos_power_source_t ainos_thermal_monitor_get_power_source(ainos_thermal_monitor_t monitor) {
    if (!monitor) return AINOS_POWER_SOURCE_UNKNOWN;

    pthread_mutex_lock(&monitor->snapshot_lock);
    ainos_power_source_t source = monitor->current_snapshot.power_source;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return source;
}

double ainos_thermal_monitor_get_battery_percentage(ainos_thermal_monitor_t monitor) {
    if (!monitor) return -1.0;

    pthread_mutex_lock(&monitor->snapshot_lock);
    double pct = monitor->current_snapshot.battery_percentage;
    pthread_mutex_unlock(&monitor->snapshot_lock);

    return pct;
}

bool ainos_thermal_monitor_is_on_battery(ainos_thermal_monitor_t monitor) {
    return ainos_thermal_monitor_get_power_source(monitor) == AINOS_POWER_SOURCE_BATTERY;
}

// ============================================================================
// Zone / Mode Utility Functions
// ============================================================================

ainos_thermal_zone_t ainos_thermal_celsius_to_zone(double celsius) {
    if (celsius >= AINOS_THERMAL_THRESHOLD_HOT_CRITICAL)
        return AINOS_THERMAL_ZONE_CRITICAL;
    if (celsius >= AINOS_THERMAL_THRESHOLD_WARM_HOT)
        return AINOS_THERMAL_ZONE_HOT;
    if (celsius >= AINOS_THERMAL_THRESHOLD_COOL_WARM)
        return AINOS_THERMAL_ZONE_WARM;
    return AINOS_THERMAL_ZONE_COOL;
}

ainos_power_mode_t ainos_thermal_zone_to_power_mode(ainos_thermal_zone_t zone) {
    switch (zone) {
        case AINOS_THERMAL_ZONE_COOL:     return AINOS_POWER_MODE_MAX;
        case AINOS_THERMAL_ZONE_WARM:     return AINOS_POWER_MODE_BALANCED;
        case AINOS_THERMAL_ZONE_HOT:      return AINOS_POWER_MODE_EFFICIENT;
        case AINOS_THERMAL_ZONE_CRITICAL: return AINOS_POWER_MODE_EMERGENCY;
        default:                          return AINOS_POWER_MODE_MAX;
    }
}

int ainos_thermal_power_mode_to_threads(ainos_power_mode_t mode) {
    switch (mode) {
        case AINOS_POWER_MODE_MAX:       return 4;
        case AINOS_POWER_MODE_BALANCED:  return 2;
        case AINOS_POWER_MODE_EFFICIENT: return 1;
        case AINOS_POWER_MODE_EMERGENCY: return 1;
        default:                         return 4;
    }
}

const char *ainos_thermal_zone_name(ainos_thermal_zone_t zone) {
    switch (zone) {
        case AINOS_THERMAL_ZONE_COOL:     return "COOL";
        case AINOS_THERMAL_ZONE_WARM:     return "WARM";
        case AINOS_THERMAL_ZONE_HOT:      return "HOT";
        case AINOS_THERMAL_ZONE_CRITICAL: return "CRITICAL";
        default:                          return "UNKNOWN";
    }
}

const char *ainos_thermal_power_mode_name(ainos_power_mode_t mode) {
    switch (mode) {
        case AINOS_POWER_MODE_MAX:       return "MAX";
        case AINOS_POWER_MODE_BALANCED:  return "BALANCED";
        case AINOS_POWER_MODE_EFFICIENT: return "EFFICIENT";
        case AINOS_POWER_MODE_EMERGENCY: return "EMERGENCY";
        default:                         return "UNKNOWN";
    }
}

const char *ainos_thermal_power_source_name(ainos_power_source_t source) {
    switch (source) {
        case AINOS_POWER_SOURCE_BATTERY: return "BATTERY";
        case AINOS_POWER_SOURCE_AC:      return "AC";
        case AINOS_POWER_SOURCE_UPS:     return "UPS";
        default:                         return "UNKNOWN";
    }
}

// ============================================================================
// AppleSMC Access
// ============================================================================

static bool ainos_thermal_smc_open(ainos_thermal_monitor_t monitor) {
    if (!monitor) return false;

    // Find the AppleSMC service
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleSMC"));

    if (!service) {
        // Try SMC (alternate name used on some Macs)
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("SMC"));
    }

    if (!service) {
        os_log_debug(monitor->log, "AppleSMC not found on this system");
        return false;
    }

    // Open a connection to the SMC
    io_connect_t connect = 0;
    kern_return_t kr = IOServiceOpen(service, mach_task_self(), 0, &connect);
    IOObjectRelease(service);

    if (kr != KERN_SUCCESS) {
        os_log_debug(monitor->log, "Failed to open AppleSMC connection: 0x%x", kr);
        return false;
    }

    monitor->smc.connect = connect;
    monitor->smc.available = true;

    os_log_info(monitor->log, "AppleSMC opened successfully");
    return true;
}

static void ainos_thermal_smc_close(ainos_thermal_monitor_t monitor) {
    if (!monitor) return;

    if (monitor->smc.connect) {
        IOServiceClose(monitor->smc.connect);
        monitor->smc.connect = 0;
    }
    monitor->smc.available = false;
}

// SMC call structure
typedef struct {
    uint32_t    key;
    ainos_smc_data_t    data;
    kern_return_t   result;
} smc_call_t;

// SMC selectors
#define SMC_CMD_READ_BYTES  5
#define SMC_CMD_READ_INDEX  8
#define SMC_CMD_DONE        9

static bool ainos_thermal_smc_call(ainos_smc_connection_t *smc,
                                   uint32_t selector,
                                   ainos_smc_data_t *data) {
    if (!smc || !smc->available) return false;

    size_t output_size = sizeof(ainos_smc_data_t);
    uint32_t input_size = sizeof(uint32_t) + sizeof(ainos_smc_data_t);

    // Build the input structure
    struct {
        uint32_t selector;
        ainos_smc_data_t data;
    } input;

    input.selector = selector;
    if (data) {
        input.data = *data;
    } else {
        memset(&input.data, 0, sizeof(ainos_smc_data_t));
    }

    // Call the SMC via IOKit
    kern_return_t kr = IOConnectCallStructMethod(
        smc->connect, 2,  // SMC method index
        &input, input_size,
        data, &output_size);

    if (kr != KERN_SUCCESS) {
        return false;
    }

    return true;
}

double ainos_thermal_smc_read_temperature(const char *key) {
    if (!key || strlen(key) != 4) return -1.0;

    // Build the SMC key
    ainos_smc_data_t data;
    memset(&data, 0, sizeof(data));

    // Convert the 4-character key to a uint32_t
    data.key = (uint32_t)key[0] << 24 |
               (uint32_t)key[1] << 16 |
               (uint32_t)key[2] << 8  |
               (uint32_t)key[3];

    // Find the SMC service
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleSMC"));
    if (!service) {
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("SMC"));
    }
    if (!service) return -1.0;

    io_connect_t connect = 0;
    kern_return_t kr = IOServiceOpen(service, mach_task_self(), 0, &connect);
    IOObjectRelease(service);
    if (kr != KERN_SUCCESS) return -1.0;

    ainos_smc_connection_t smc_conn = {
        .connect = connect,
        .available = true
    };

    // Read the temperature value
    ainos_smc_data_t result;
    memset(&result, 0, sizeof(result));
    result.key = data.key;

    bool success = ainos_thermal_smc_call(&smc_conn, SMC_CMD_READ_BYTES, &result);

    IOServiceClose(connect);

    if (!success) return -1.0;

    // Parse the temperature based on the data type
    // Temperature types are typically "sp78" (signed 7.8 fixed-point)
    if (result.data_size >= 2) {
        // sp78 format: first byte is integer part, second byte is fractional
        int16_t fixed = (int16_t)((result.data[0] << 8) | result.data[1]);
        return (double)fixed / 256.0;
    }

    return -1.0;
}

bool ainos_thermal_smc_read_key(const char *key, uint8_t *data_out, size_t *length_out) {
    if (!key || !data_out || !length_out) return false;

    ainos_smc_data_t data;
    memset(&data, 0, sizeof(data));
    data.key = (uint32_t)key[0] << 24 |
               (uint32_t)key[1] << 16 |
               (uint32_t)key[2] << 8  |
               (uint32_t)key[3];

    // Find the SMC service
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleSMC"));
    if (!service) {
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("SMC"));
    }
    if (!service) return false;

    io_connect_t connect = 0;
    kern_return_t kr = IOServiceOpen(service, mach_task_self(), 0, &connect);
    IOObjectRelease(service);
    if (kr != KERN_SUCCESS) return false;

    ainos_smc_connection_t smc_conn = {
        .connect = connect,
        .available = true
    };

    ainos_smc_data_t result;
    memset(&result, 0, sizeof(result));
    result.key = data.key;

    bool success = ainos_thermal_smc_call(&smc_conn, SMC_CMD_READ_BYTES, &result);
    IOServiceClose(connect);

    if (!success) return false;

    size_t copy_size = result.data_size;
    if (copy_size > *length_out) copy_size = *length_out;
    memcpy(data_out, result.data, copy_size);
    *length_out = copy_size;

    return true;
}

// ============================================================================
// IORegistry Thermal Zone Access
// ============================================================================

int ainos_thermal_ioregistry_get_thermal_level(void) {
    // Query the IORegistry for the thermal level
    // This is available on Apple Silicon Macs

    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleARMPE"));
    if (!service) {
        // Try alternative
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("arm-io"));
    }
    if (!service) return -1;

    CFStringRef key = CFSTR("thermal-level");
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key,
        kCFAllocatorDefault, 0);
    IOObjectRelease(service);

    if (!value) return -1;

    int level = -1;
    if (CFNumberGetTypeID() == CFGetTypeID(value)) {
        CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &level);
    }
    CFRelease(value);

    return level;
}

double ainos_thermal_ioregistry_get_cpu_temperature(void) {
    // On Apple Silicon Macs, the CPU temperature is available in the
    // IORegistry under the "thermal-zones" entry.

    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleARMPE"));
    if (!service) {
        // Try the thermal zones directly
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("thermal-zones"));
    }
    if (!service) {
        // Try the SoC temperature service
        service = IOServiceGetMatchingService(
            kIOMasterPortDefault,
            IOServiceNameMatching("soctemp"));
    }
    if (!service) return -1.0;

    // Try to read the CPU temperature property
    CFStringRef key = CFSTR("cpu_die");
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key,
        kCFAllocatorDefault, 0);

    if (!value) {
        // Try alternative key
        key = CFSTR("cpu-temp");
        value = IORegistryEntryCreateCFProperty(service, key,
            kCFAllocatorDefault, 0);
    }

    IOObjectRelease(service);

    if (!value) return -1.0;

    double temp = -1.0;
    if (CFNumberGetTypeID() == CFGetTypeID(value)) {
        CFNumberGetValue((CFNumberRef)value, kCFNumberDoubleType, &temp);
    }

    CFRelease(value);

    // The value might be in millidegrees Celsius
    if (temp > 200) {
        temp /= 1000.0;
    }

    return temp;
}

double ainos_thermal_ioregistry_get_gpu_temperature(void) {
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceNameMatching("soctemp"));
    if (!service) return -1.0;

    CFStringRef key = CFSTR("gpu_die");
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key,
        kCFAllocatorDefault, 0);
    IOObjectRelease(service);

    if (!value) return -1.0;

    double temp = -1.0;
    if (CFNumberGetTypeID() == CFGetTypeID(value)) {
        CFNumberGetValue((CFNumberRef)value, kCFNumberDoubleType, &temp);
    }
    CFRelease(value);

    if (temp > 200) temp /= 1000.0;
    return temp;
}

// ============================================================================
// Power Source IOKit Access
// ============================================================================

ainos_power_source_t ainos_thermal_ioregistry_get_power_source(void) {
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (!power_info) return AINOS_POWER_SOURCE_UNKNOWN;

    ainos_power_source_t source = AINOS_POWER_SOURCE_UNKNOWN;
    CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
    if (sources) {
        if (CFArrayGetCount(sources) > 0) {
            CFDictionaryRef desc = IOPSGetPowerSourceDescription(power_info,
                CFArrayGetValueAtIndex(sources, 0));
            if (desc) {
                CFStringRef state = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSPowerSourceStateKey));
                if (state) {
                    if (CFStringCompare(state, CFSTR(kIOPSACPowerValue), 0) == kCFCompareEqualTo) {
                        source = AINOS_POWER_SOURCE_AC;
                    } else if (CFStringCompare(state, CFSTR(kIOPSBatteryPowerValue), 0) == kCFCompareEqualTo) {
                        source = AINOS_POWER_SOURCE_BATTERY;
                    }
                }
            }
        }
        CFRelease(sources);
    }
    CFRelease(power_info);

    return source;
}

double ainos_thermal_ioregistry_get_battery_percentage(void) {
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (!power_info) return -1.0;

    double pct = -1.0;
    CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
    if (sources) {
        if (CFArrayGetCount(sources) > 0) {
            CFDictionaryRef desc = IOPSGetPowerSourceDescription(power_info,
                CFArrayGetValueAtIndex(sources, 0));
            if (desc) {
                CFNumberRef cur = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSCurrentCapacityKey));
                CFNumberRef max = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSMaxCapacityKey));
                if (cur && max) {
                    int c = 0, m = 0;
                    CFNumberGetValue(cur, kCFNumberIntType, &c);
                    CFNumberGetValue(max, kCFNumberIntType, &m);
                    if (m > 0) pct = (double)c / (double)m * 100.0;
                }
            }
        }
        CFRelease(sources);
    }
    CFRelease(power_info);

    return pct;
}

int ainos_thermal_ioregistry_get_battery_cycle_count(void) {
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (!power_info) return -1;

    int cycles = -1;
    CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
    if (sources) {
        if (CFArrayGetCount(sources) > 0) {
            CFDictionaryRef desc = IOPSGetPowerSourceDescription(power_info,
                CFArrayGetValueAtIndex(sources, 0));
            if (desc) {
                CFNumberRef cycle_count = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSBatteryCycleCountKey));
                if (cycle_count) {
                    CFNumberGetValue(cycle_count, kCFNumberIntType, &cycles);
                }
            }
        }
        CFRelease(sources);
    }
    CFRelease(power_info);

    return cycles;
}

bool ainos_thermal_ioregistry_is_battery_charging(void) {
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (!power_info) return false;

    bool charging = false;
    CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
    if (sources) {
        if (CFArrayGetCount(sources) > 0) {
            CFDictionaryRef desc = IOPSGetPowerSourceDescription(power_info,
                CFArrayGetValueAtIndex(sources, 0));
            if (desc) {
                CFBooleanRef is_charging = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSIsChargingKey));
                if (is_charging) {
                    charging = CFBooleanGetValue(is_charging);
                }
            }
        }
        CFRelease(sources);
    }
    CFRelease(power_info);

    return charging;
}

bool ainos_thermal_ioregistry_is_battery_fully_charged(void) {
    CFTypeRef power_info = IOPSCopyPowerSourcesInfo();
    if (!power_info) return false;

    bool charged = false;
    CFArrayRef sources = IOPSCopyPowerSourcesList(power_info);
    if (sources) {
        if (CFArrayGetCount(sources) > 0) {
            CFDictionaryRef desc = IOPSGetPowerSourceDescription(power_info,
                CFArrayGetValueAtIndex(sources, 0));
            if (desc) {
                CFBooleanRef is_charged = CFDictionaryGetValue(desc,
                    CFSTR(kIOPSIsChargedKey));
                if (is_charged) {
                    charged = CFBooleanGetValue(is_charged);
                }
            }
        }
        CFRelease(sources);
    }
    CFRelease(power_info);

    return charged;
}

// ============================================================================
// Thermal Notification
// ============================================================================

dispatch_source_t ainos_thermal_create_notification_source(
    dispatch_queue_t queue,
    dispatch_block_t handler) {
    // Create a dispatch source for thermal notifications
    // This uses DISPATCH_SOURCE_TYPE_DATA_ADD to receive thermal events

    dispatch_source_t source = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_DATA_ADD, 0, 0, queue);

    if (!source) return NULL;

    if (handler) {
        dispatch_source_set_event_handler(source, handler);
    }

    return source;
}

int ainos_thermal_get_system_thermal_pressure(void) {
    // Query the system's thermal pressure level
    // This is available on macOS 11+ (Big Sur)

    // Use sysctl to read thermal pressure
    int pressure = 0;
    size_t size = sizeof(pressure);
    int mib[] = { CTL_HW, HW_THERMAL_PRESSURE };

    if (sysctl(mib, 2, &pressure, &size, NULL, 0) == 0) {
        return pressure;
    }

    // Fallback: try IORegistry
    int level = ainos_thermal_ioregistry_get_thermal_level();
    if (level >= 0) return level;

    // Fallback: read from thermal zone
    io_service_t service = IOServiceGetMatchingService(
        kIOMasterPortDefault,
        IOServiceMatching("AppleARMPE"));
    if (!service) return 0;

    CFStringRef key = CFSTR("thermal-pressure");
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key,
        kCFAllocatorDefault, 0);
    IOObjectRelease(service);

    if (value) {
        if (CFNumberGetTypeID() == CFGetTypeID(value)) {
            CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &pressure);
        }
        CFRelease(value);
    }

    return pressure;
}

// ============================================================================
// Integration with Power Policy System
// ============================================================================

bool ainos_thermal_apply_policy(const ainos_thermal_snapshot_t *snapshot) {
    if (!snapshot) return false;

    // Write the policy state to the shared file
    // This is the same file that the Rust daemon reads in its
    // macOS-specific thermal integration.

    mkdir("/var/run/ainos", 0755);

    int fd = open(AINOS_THERMAL_POLICY_FILE,
                  O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return false;

    char buffer[256];
    int len = snprintf(buffer, sizeof(buffer),
        "{\"cpu_temp\":%.1f,\"zone\":\"%s\",\"mode\":\"%s\",\"threads\":%d}\n",
        snapshot->cpu_temp_celsius,
        ainos_thermal_zone_name(snapshot->zone),
        ainos_thermal_power_mode_name(snapshot->power_mode),
        snapshot->recommended_threads);

    bool success = (write(fd, buffer, (size_t)len) == (ssize_t)len);
    close(fd);

    return success;
}

bool ainos_thermal_read_policy(ainos_power_mode_t *mode_out,
                               int *threads_out) {
    if (!mode_out || !threads_out) return false;

    int fd = open(AINOS_THERMAL_POLICY_FILE, O_RDONLY);
    if (fd < 0) return false;

    char buffer[256];
    ssize_t n = read(fd, buffer, sizeof(buffer) - 1);
    close(fd);

    if (n <= 0) return false;
    buffer[n] = '\0';

    // Parse the JSON line (simple parsing, not a full JSON parser)
    // Expected format: {"cpu_temp":45.2,"zone":"COOL","mode":"MAX","threads":4}
    char *mode_str = strstr(buffer, "\"mode\":\"");
    char *threads_str = strstr(buffer, "\"threads\":");
    char *zone_str = strstr(buffer, "\"zone\":\"");

    if (mode_str) {
        mode_str += 8; // skip past "mode":""
        char *end = strchr(mode_str, '"');
        if (end) *end = '\0';

        if (strcmp(mode_str, "MAX") == 0) *mode_out = AINOS_POWER_MODE_MAX;
        else if (strcmp(mode_str, "BALANCED") == 0) *mode_out = AINOS_POWER_MODE_BALANCED;
        else if (strcmp(mode_str, "EFFICIENT") == 0) *mode_out = AINOS_POWER_MODE_EFFICIENT;
        else if (strcmp(mode_str, "EMERGENCY") == 0) *mode_out = AINOS_POWER_MODE_EMERGENCY;
    }

    if (threads_str) {
        threads_str += 10; // skip past "threads":
        *threads_out = atoi(threads_str);
    }

    return true;
}

// ============================================================================
// Initialization (constructor)
// ============================================================================

// __attribute__((constructor)) static void ainos_thermal_init(void) {
//     // This runs automatically when the library is loaded.
//     // No initialization needed at load time.
// }

// ============================================================================
// End of ainos_thermal.c
// ============================================================================