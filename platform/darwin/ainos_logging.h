// Ainos OS - macOS Unified Logging Interface
// Public header for the unified logging subsystem.
// Wraps Apple's os_log API with privacy classification and structured logging.

#ifndef AINOS_LOGGING_H
#define AINOS_LOGGING_H

#include <os/log.h>
#include <stdint.h>
#include <stdbool.h>
#include <dispatch/dispatch.h>

// ============================================================================
// Log Subsystem and Categories
// ============================================================================

// The main log subsystem identifier for all Ainos components.
#define AINOS_LOG_SUBSYSTEM "com.ainos.daemon"

// Predefined log categories matching Ainos OS subsystems.
// These are used with os_log_create() to create category-specific log objects.
#define AINOS_LOG_CATEGORY_DAEMON  "daemon"
#define AINOS_LOG_CATEGORY_RUNTIME "runtime"
#define AINOS_LOG_CATEGORY_POLICY  "policy"
#define AINOS_LOG_CATEGORY_FS      "fs"
#define AINOS_LOG_CATEGORY_NETWORK "network"

// ============================================================================
// Log Levels
// ============================================================================

// Log levels mirror os_log_type_t but are redefined here for decoupling
// from the Apple SDK header version.
typedef enum {
    AINOS_LOG_LEVEL_DEBUG   = 0x00,  // Debug-level message (os_log_debug)
    AINOS_LOG_LEVEL_INFO    = 0x01,  // Informational message (os_log_info)
    AINOS_LOG_LEVEL_ERROR   = 0x10,  // Error-level message (os_log_error)
    AINOS_LOG_LEVEL_FAULT   = 0x11,  // Fault-level message (os_log_fault)
} ainos_log_level_t;

// ============================================================================
// Log Handle
// ============================================================================

// Opaque handle to a log object with a specific subsystem and category.
// Created via ainos_log_create() and released via ainos_log_release().
typedef struct ainos_log_s *ainos_log_t;

// ============================================================================
// Privacy Classification
// ============================================================================

// Privacy classification for log arguments.
// Maps to os_log's privacy controls:
//   - Public:        Always visible in logs (no redaction)
//   - Private:       Redacted in release logs, visible in diagnostics
//   - Sensitive:     Always redacted unless explicitly authorized
//   - Auto:          Let os_log infer privacy from the format specifier
typedef enum {
    AINOS_LOG_PRIVACY_AUTO      = 0,  // Let os_log decide
    AINOS_LOG_PRIVACY_PUBLIC    = 1,  // {public} – always visible
    AINOS_LOG_PRIVACY_PRIVATE   = 2,  // {private} – redacted in release
    AINOS_LOG_PRIVACY_SENSITIVE = 3,  // {sensitive} – always redacted
} ainos_log_privacy_t;

// ============================================================================
// Structured Log Entry
// ============================================================================

// A structured log entry with metadata.
// Used for machine-parseable logging with JSON-like key-value pairs.
#define AINOS_LOG_MAX_FIELDS 16

typedef struct {
    const char *key;
    const char *value;
    ainos_log_privacy_t privacy;
} ainos_log_field_t;

typedef struct {
    os_log_t    log;           // Underlying os_log_t object
    os_log_type_t type;        // Log level mapped to os_log_type_t
    uint64_t    timestamp_ns;  // Nanosecond timestamp
    const char *file;          // Source file name
    int         line;          // Source line number
    const char *function;      // Function name
    const char *message;       // Log message (format string)
    ainos_log_field_t fields[AINOS_LOG_MAX_FIELDS]; // Key-value pairs
    int         field_count;   // Number of populated fields
} ainos_log_entry_t;

// ============================================================================
// Function Prototypes
// ============================================================================

// Create a log object for the given subsystem and category.
// Returns NULL on failure.
// The returned object must be released with ainos_log_release().
ainos_log_t ainos_log_create(const char *subsystem, const char *category);

// Convenience wrappers that create logs under the Ainos subsystem.
ainos_log_t ainos_log_create_daemon(void);
ainos_log_t ainos_log_create_runtime(void);
ainos_log_t ainos_log_create_policy(void);
ainos_log_t ainos_log_create_fs(void);
ainos_log_t ainos_log_create_network(void);

// Retain (increment reference count) a log object.
// Returns the same pointer.
ainos_log_t ainos_log_retain(ainos_log_t log);

// Release (decrement reference count) a log object.
// When the count reaches zero, the object is deallocated.
void ainos_log_release(ainos_log_t log);

// ============================================================================
// Logging Functions
// ============================================================================

// Basic logging functions for each level.
// These accept a printf-style format string and variadic arguments.
// Privacy classification is applied to the format string via os_log's
// %{public}@, %{private}@, and %{sensitive}@ specifiers.
void ainos_log_debug(ainos_log_t log, const char *format, ...)
    __attribute__((format(printf, 2, 3)));
void ainos_log_info(ainos_log_t log, const char *format, ...)
    __attribute__((format(printf, 2, 3)));
void ainos_log_error(ainos_log_t log, const char *format, ...)
    __attribute__((format(printf, 2, 3)));
void ainos_log_fault(ainos_log_t log, const char *format, ...)
    __attribute__((format(printf, 2, 3)));

// ============================================================================
// Structured Logging
// ============================================================================

// Log with structured key-value fields.
// Example:
//   ainos_log_field_t fields[] = {
//       { "model", "phi-3-mini", AINOS_LOG_PRIVACY_PUBLIC },
//       { "user_id", "abc123", AINOS_LOG_PRIVACY_PRIVATE },
//   };
//   ainos_log_info_fields(log, "Model loaded", fields, 2);
void ainos_log_debug_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count);
void ainos_log_info_fields(ainos_log_t log, const char *message,
                           const ainos_log_field_t *fields, int count);
void ainos_log_error_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count);
void ainos_log_fault_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count);

// ============================================================================
// Signpost (Performance Tracing)
// ============================================================================

// Signpost events for performance instrumentation.
// These are visible in Instruments (os_signpost).
typedef enum {
    AINOS_LOG_SIGNPOST_INFERENCE = 1,
    AINOS_LOG_SIGNPOST_MODEL_LOAD = 2,
    AINOS_LOG_SIGNPOST_IPC_HANDLE = 3,
    AINOS_LOG_SIGNPOST_THERMAL_CHECK = 4,
} ainos_signpost_id_t;

// Emit a signpost begin event.
void ainos_signpost_begin(ainos_log_t log, ainos_signpost_id_t event_id,
                          const char *format, ...)
    __attribute__((format(printf, 3, 4)));

// Emit a signpost end event.
void ainos_signpost_end(ainos_log_t log, ainos_signpost_id_t event_id,
                        const char *format, ...)
    __attribute__((format(printf, 3, 4)));

// ============================================================================
// Utility Functions
// ============================================================================

// Check if logging at the given level is enabled for the log object.
// This can be used to avoid expensive argument evaluation when logging
// is disabled.
bool ainos_log_is_enabled(ainos_log_t log, ainos_log_level_t level);

// Flush any pending log messages.
// Under normal circumstances this is not needed, but can be useful
// before a crash to ensure all messages are written.
void ainos_log_flush(void);

// Get the current system log level for the Ainos subsystem.
// Returns AINOS_LOG_LEVEL_INFO by default.
ainos_log_level_t ainos_log_get_level(void);

// Convert a string level name to ainos_log_level_t.
// Returns AINOS_LOG_LEVEL_INFO for unknown strings.
ainos_log_level_t ainos_log_level_from_string(const char *name);

// Convert ainos_log_level_t to a human-readable string.
const char *ainos_log_level_to_string(ainos_log_level_t level);

// Convert ainos_log_privacy_t to a format specifier prefix.
// Returns the os_log privacy annotation string (e.g., "{public}").
const char *ainos_log_privacy_to_format(ainos_log_privacy_t privacy);

#endif /* AINOS_LOGGING_H */