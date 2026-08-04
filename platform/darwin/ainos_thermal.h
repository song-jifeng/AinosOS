// Ainos OS - macOS Thermal Monitoring Interface
// Public header for IOKit-based thermal monitoring, power source
// detection, and integration with the Ainos power policy system.

#ifndef AINOS_THERMAL_H
#define AINOS_THERMAL_H

#include <stdint.h>
#include <stdbool.h>
#include <dispatch/dispatch.h>

// ============================================================================
// Temperature Thresholds (matching the existing Ainos power policy system)
// ============================================================================

// These thresholds align with the values in:
//   - kernel/ai-scheduler-main.c
//   - ai-runtime/power-policy/power_policy.cpp
//   - system-services/ai-daemon/src/thermal.rs
#define AINOS_THERMAL_THRESHOLD_COOL_WARM     70.0   // °C
#define AINOS_THERMAL_THRESHOLD_WARM_HOT      85.0   // °C
#define AINOS_THERMAL_THRESHOLD_HOT_CRITICAL  95.0   // °C

// ============================================================================
// Thermal Zone Enumeration
// ============================================================================

// Thermal zone classification matching the cross-platform Ainos definitions.
typedef enum {
    AINOS_THERMAL_ZONE_COOL     = 0,  // < 70°C
    AINOS_THERMAL_ZONE_WARM     = 1,  // 70-85°C
    AINOS_THERMAL_ZONE_HOT      = 2,  // 85-95°C
    AINOS_THERMAL_ZONE_CRITICAL = 3,  // > 95°C
} ainos_thermal_zone_t;

// ============================================================================
// Power Mode Enumeration
// ============================================================================

// Power mode matching the cross-platform Ainos definitions.
typedef enum {
    AINOS_POWER_MODE_MAX        = 0,  // Full speed: 4 threads, FP32
    AINOS_POWER_MODE_BALANCED   = 1,  // Balanced: 2 threads, FP16
    AINOS_POWER_MODE_EFFICIENT  = 2,  // Efficient: 1 thread, INT8
    AINOS_POWER_MODE_EMERGENCY  = 3,  // Emergency: 1 thread, INT4
} ainos_power_mode_t;

// ============================================================================
// Power Source Type
// ============================================================================

typedef enum {
    AINOS_POWER_SOURCE_UNKNOWN = 0,
    AINOS_POWER_SOURCE_BATTERY = 1,
    AINOS_POWER_SOURCE_AC      = 2,
    AINOS_POWER_SOURCE_UPS     = 3,
} ainos_power_source_t;

// ============================================================================
// Thermal Snapshot
// ============================================================================

// A snapshot of the current thermal state.
// This is the macOS equivalent of thermal::ThermalSnapshot in Rust.
typedef struct {
    double              cpu_temp_celsius;       // Current CPU temperature
    double              gpu_temp_celsius;       // Current GPU temperature (0 if unavailable)
    double              ambient_temp_celsius;   // Ambient / enclosure temperature
    ainos_thermal_zone_t zone;                  // Derived thermal zone
    ainos_power_mode_t   power_mode;            // Suggested power mode
    int                 recommended_threads;    // Recommended thread count
    bool                sensor_available;       // Whether thermal sensors are accessible
    bool                throttle_active;        // Whether thermal throttling is active
    ainos_power_source_t power_source;          // Current power source
    double              battery_percentage;     // Battery charge (0-100, -1 if AC)
    int                 battery_cycle_count;    // Battery cycle count (-1 if unavailable)
    uint64_t            timestamp_ns;           // Nanosecond timestamp of the snapshot
} ainos_thermal_snapshot_t;

// ============================================================================
// Thermal Monitor
// ============================================================================

// Opaque handle to the thermal monitor.
typedef struct ainos_thermal_monitor_s *ainos_thermal_monitor_t;

// Thermal change callback type.
// Called when the thermal zone or power mode changes.
// Parameters:
//   context:    User-provided context pointer
//   snapshot:   Current thermal snapshot
//   old_zone:   Previous thermal zone
typedef void (*ainos_thermal_callback_t)(void *context,
                                         const ainos_thermal_snapshot_t *snapshot,
                                         ainos_thermal_zone_t old_zone);

// ============================================================================
// Function Prototypes
// ============================================================================

// Create and initialize the thermal monitor.
// This opens connections to IOKit (IOServiceGetMatchingServices) and
// begins monitoring the system power source.
// Returns NULL on failure.
ainos_thermal_monitor_t ainos_thermal_monitor_create(void);

// Create the thermal monitor with custom polling interval.
// interval_ms: polling interval in milliseconds (default 2000)
ainos_thermal_monitor_t ainos_thermal_monitor_create_with_interval(uint32_t interval_ms);

// Destroy the thermal monitor and release all resources.
// This stops the dispatch source and closes IOKit connections.
void ainos_thermal_monitor_destroy(ainos_thermal_monitor_t monitor);

// ============================================================================
// Configuration
// ============================================================================

// Set custom temperature thresholds.
// Passing 0 for any threshold keeps the current value.
void ainos_thermal_monitor_set_thresholds(ainos_thermal_monitor_t monitor,
                                          double cool_warm,
                                          double warm_hot,
                                          double hot_critical);

// Set the polling interval in milliseconds.
void ainos_thermal_monitor_set_interval(ainos_thermal_monitor_t monitor,
                                        uint32_t interval_ms);

// Register a callback for thermal zone changes.
// The callback is invoked on the monitor's internal dispatch queue.
// Passing NULL for callback unregisters the previous callback.
void ainos_thermal_monitor_set_callback(ainos_thermal_monitor_t monitor,
                                        ainos_thermal_callback_t callback,
                                        void *context);

// ============================================================================
// Monitoring Control
// ============================================================================

// Start the thermal monitoring dispatch source.
// Returns true if monitoring started successfully.
bool ainos_thermal_monitor_start(ainos_thermal_monitor_t monitor);

// Stop the thermal monitoring dispatch source.
void ainos_thermal_monitor_stop(ainos_thermal_monitor_t monitor);

// ============================================================================
// Query Functions
// ============================================================================

// Get the current thermal snapshot.
// This performs a synchronous read of the latest cached values.
// Returns true if the snapshot was populated, false if monitoring is not active.
bool ainos_thermal_monitor_get_snapshot(ainos_thermal_monitor_t monitor,
                                        ainos_thermal_snapshot_t *snapshot_out);

// Force an immediate sensor read and return the result.
// This bypasses the cache and reads directly from IOKit.
// Returns true if the read was successful.
bool ainos_thermal_monitor_read_now(ainos_thermal_monitor_t monitor,
                                    ainos_thermal_snapshot_t *snapshot_out);

// Get the current thermal zone.
ainos_thermal_zone_t ainos_thermal_monitor_get_zone(ainos_thermal_monitor_t monitor);

// Get the current power mode.
ainos_power_mode_t ainos_thermal_monitor_get_power_mode(ainos_thermal_monitor_t monitor);

// Get the recommended thread count.
int ainos_thermal_monitor_get_recommended_threads(ainos_thermal_monitor_t monitor);

// ============================================================================
// Power Source Monitoring
// ============================================================================

// Get the current power source (battery / AC / UPS).
ainos_power_source_t ainos_thermal_monitor_get_power_source(ainos_thermal_monitor_t monitor);

// Get the current battery percentage (0-100, -1 if on AC).
double ainos_thermal_monitor_get_battery_percentage(ainos_thermal_monitor_t monitor);

// Check if the system is running on battery power.
bool ainos_thermal_monitor_is_on_battery(ainos_thermal_monitor_t monitor);

// ============================================================================
// Zone / Mode Utility Functions
// ============================================================================

// Convert a temperature in Celsius to a thermal zone.
ainos_thermal_zone_t ainos_thermal_celsius_to_zone(double celsius);

// Convert a thermal zone to the recommended power mode.
ainos_power_mode_t ainos_thermal_zone_to_power_mode(ainos_thermal_zone_t zone);

// Convert a power mode to the recommended thread count.
int ainos_thermal_power_mode_to_threads(ainos_power_mode_t mode);

// Get a human-readable name for a thermal zone.
const char *ainos_thermal_zone_name(ainos_thermal_zone_t zone);

// Get a human-readable name for a power mode.
const char *ainos_thermal_power_mode_name(ainos_power_mode_t mode);

// Get a human-readable name for a power source.
const char *ainos_thermal_power_source_name(ainos_power_source_t source);

// ============================================================================
// AppleSMC (System Management Controller) Access
// ============================================================================

// Read a temperature sensor value from AppleSMC via IOKit.
// Returns the temperature in Celsius, or -1 if the key is not available.
// Common keys:
//   "TC0p" - CPU 0 proximity
//   "TC0P" - CPU 0 proximity (alternate)
//   "TC0D" - CPU 0 die
//   "TC1p" - CPU 1 proximity
//   "TG0p" - GPU 0 proximity
//   "TG0D" - GPU 0 die
//   "TA0p" - Ambient / enclosure
//   "TB0T" - Battery temperature
//   "TW0p" - Wireless module
double ainos_thermal_smc_read_temperature(const char *key);

// Read a raw SMC key value.
// Returns true if the key was read successfully.
bool ainos_thermal_smc_read_key(const char *key, uint8_t *data_out, size_t *length_out);

// ============================================================================
// IORegistry Thermal Zone Access
// ============================================================================

// Read the current thermal level from the IORegistry.
// Returns a value from 0 (nominal) to 3 (critical).
int ainos_thermal_ioregistry_get_thermal_level(void);

// Read the CPU temperature from IORegistry (AppleARM64 / Apple Silicon).
// Returns the temperature in Celsius, or -1 if unavailable.
// Apple Silicon SoCs expose temperature via the "thermal-zones" node.
double ainos_thermal_ioregistry_get_cpu_temperature(void);

// Read the GPU temperature from IORegistry.
// Returns the temperature in Celsius, or -1 if unavailable.
double ainos_thermal_ioregistry_get_gpu_temperature(void);

// ============================================================================
// Power Source IOKit Access
// ============================================================================

// Read the current power source state from IOKit.
// Returns AINOS_POWER_SOURCE_UNKNOWN on failure.
ainos_power_source_t ainos_thermal_ioregistry_get_power_source(void);

// Read the battery percentage from IOKit.
// Returns -1 if unavailable or on AC power.
double ainos_thermal_ioregistry_get_battery_percentage(void);

// Read the battery cycle count from IOKit.
// Returns -1 if unavailable.
int ainos_thermal_ioregistry_get_battery_cycle_count(void);

// Check if the battery is currently charging.
bool ainos_thermal_ioregistry_is_battery_charging(void);

// Check if the battery is fully charged.
bool ainos_thermal_ioregistry_is_battery_fully_charged(void);

// ============================================================================
// Thermal Notification
// ============================================================================

// Register for system thermal notifications using dispatch_source.
// This receives notifications from the kernel's thermal framework.
// Returns a dispatch source that must be resumed and later cancelled.
// Pass NULL for handler to unregister the previous handler.
dispatch_source_t ainos_thermal_create_notification_source(
    dispatch_queue_t queue,
    dispatch_block_t handler);

// Check the current system thermal pressure level (macOS 11+).
// Returns a value from 0 (nominal) to 3 (critical).
// This uses the IOKit thermal notification mechanism.
int ainos_thermal_get_system_thermal_pressure(void);

// ============================================================================
// Integration with Power Policy System
// ============================================================================

// Apply the thermal state to the Ainos power policy system.
// This writes the recommended power mode and thread count to a shared
// memory segment or file for the Rust daemon to read.
// Returns true if the policy was updated successfully.
bool ainos_thermal_apply_policy(const ainos_thermal_snapshot_t *snapshot);

// Read the currently applied power policy.
// Returns true if the policy was read successfully.
bool ainos_thermal_read_policy(ainos_power_mode_t *mode_out,
                               int *threads_out);

#endif /* AINOS_THERMAL_H */