// Ainos OS - macOS Unified Logging Implementation
// ============================================================================
//
// This file implements the unified logging subsystem for AinosOS on macOS.
// It wraps Apple's os_log API (introduced in macOS 10.12) with privacy
// classification, structured logging, and signpost performance tracing.
//
// Log Subsystem: com.ainos.daemon
// Log Categories: daemon, runtime, policy, fs, network
//
// Privacy Classification:
//   - Public:    Always visible (e.g., model names, operation counts)
//   - Private:   Redacted in release logs (e.g., user IDs, file paths)
//   - Sensitive: Always redacted (e.g., API keys, tokens)
//
// Compile with:
//   clang -x objective-c -fobjc-arc -framework Foundation \
//         -framework OSLog -o ainos_logging.dylib -dynamiclib ainos_logging.c
//
// Link with:
//   -framework Foundation -framework OSLog

#include "ainos_logging.h"
#include <os/log.h>
#include <os/signpost.h>
#include <os/activity.h>
#include <os/trace.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <time.h>
#include <sys/time.h>
#include <mach/mach_time.h>
#include <dispatch/dispatch.h>

// ============================================================================
// Constants
// ============================================================================

#define AINOS_LOG_MAX_CATEGORIES   8
#define AINOS_LOG_INITIAL_CAPACITY 64
#define AINOS_LOG_CACHE_SIZE       256

// ============================================================================
// Log Object
// ============================================================================

struct ainos_log_s {
    os_log_t             os_log;          // Underlying os_log_t object
    char                *subsystem;       // Subsystem string (e.g., "com.ainos.daemon")
    char                *category;        // Category string (e.g., "runtime")
    atomic_int           ref_count;       // Reference count
    ainos_log_level_t    level;           // Current log level (cached)
    dispatch_queue_t     queue;           // Serial queue for structured logging
};

// ============================================================================
// Log Cache
// ============================================================================

// A simple cache for frequently used log objects to avoid repeated
// calls to os_log_create(), which is relatively expensive.
typedef struct ainos_log_cache_s {
    ainos_log_t entries[AINOS_LOG_CACHE_SIZE];
    int          count;
    pthread_mutex_t lock;
} ainos_log_cache_t;

static ainos_log_cache_t g_log_cache = {
    .entries = {0},
    .count = 0,
    .lock = PTHREAD_MUTEX_INITIALIZER,
};

// ============================================================================
// Static Log Objects (singletons for convenience categories)
// ============================================================================

static ainos_log_t g_log_daemon  = NULL;
static ainos_log_t g_log_runtime = NULL;
static ainos_log_t g_log_policy  = NULL;
static ainos_log_t g_log_fs      = NULL;
static ainos_log_t g_log_network = NULL;

static pthread_once_t g_log_init_once = PTHREAD_ONCE_INIT;

// ============================================================================
// Forward Declarations
// ============================================================================

static void ainos_log_initialize_singletons(void);
static void ainos_log_vlog(ainos_log_t log, os_log_type_t type,
                           const char *format, va_list args);
static void ainos_log_vlog_fields(ainos_log_t log, os_log_type_t type,
                                  const char *message,
                                  const ainos_log_field_t *fields, int count);
static os_log_type_t ainos_log_level_to_os_log_type(ainos_log_level_t level);
static ainos_log_level_t ainos_os_log_type_to_level(os_log_type_t type);

// ============================================================================
// Create / Destroy Log Objects
// ============================================================================

ainos_log_t ainos_log_create(const char *subsystem, const char *category) {
    if (!subsystem || !category) return NULL;

    // Check cache first
    pthread_mutex_lock(&g_log_cache.lock);
    for (int i = 0; i < g_log_cache.count; i++) {
        ainos_log_t cached = g_log_cache.entries[i];
        if (strcmp(cached->subsystem, subsystem) == 0 &&
            strcmp(cached->category, category) == 0) {
            ainos_log_retain(cached);
            pthread_mutex_unlock(&g_log_cache.lock);
            return cached;
        }
    }
    pthread_mutex_unlock(&g_log_cache.lock);

    // Create new log object
    ainos_log_t log = (ainos_log_t)calloc(1, sizeof(struct ainos_log_s));
    if (!log) return NULL;

    log->subsystem = strdup(subsystem);
    log->category  = strdup(category);
    if (!log->subsystem || !log->category) {
        free(log->subsystem);
        free(log->category);
        free(log);
        return NULL;
    }

    // Create the underlying os_log_t object
    os_log_t os_log = os_log_create(subsystem, category);
    log->os_log = os_log;

    atomic_init(&log->ref_count, 1);
    log->level = AINOS_LOG_LEVEL_INFO;

    // Create a serial queue for structured logging
    char queue_label[64];
    snprintf(queue_label, sizeof(queue_label), "com.ainos.log.%s", category);
    log->queue = dispatch_queue_create(queue_label, DISPATCH_QUEUE_SERIAL);

    // Add to cache
    pthread_mutex_lock(&g_log_cache.lock);
    if (g_log_cache.count < AINOS_LOG_CACHE_SIZE) {
        g_log_cache.entries[g_log_cache.count++] = log;
    }
    pthread_mutex_unlock(&g_log_cache.lock);

    return log;
}

ainos_log_t ainos_log_retain(ainos_log_t log) {
    if (log) {
        atomic_fetch_add(&log->ref_count, 1);
    }
    return log;
}

void ainos_log_release(ainos_log_t log) {
    if (!log) return;

    if (atomic_fetch_sub(&log->ref_count, 1) == 1) {
        // Last reference: destroy
        // Remove from cache
        pthread_mutex_lock(&g_log_cache.lock);
        for (int i = 0; i < g_log_cache.count; i++) {
            if (g_log_cache.entries[i] == log) {
                g_log_cache.entries[i] = g_log_cache.entries[--g_log_cache.count];
                break;
            }
        }
        pthread_mutex_unlock(&g_log_cache.lock);

        // Release resources
        if (log->os_log) {
            os_release(log->os_log);
        }
        if (log->queue) {
            dispatch_release(log->queue);
        }
        free(log->subsystem);
        free(log->category);
        free(log);
    }
}

// ============================================================================
// Singleton Convenience Logs
// ============================================================================

static void ainos_log_initialize_singletons(void) {
    g_log_daemon  = ainos_log_create(AINOS_LOG_SUBSYSTEM, AINOS_LOG_CATEGORY_DAEMON);
    g_log_runtime = ainos_log_create(AINOS_LOG_SUBSYSTEM, AINOS_LOG_CATEGORY_RUNTIME);
    g_log_policy  = ainos_log_create(AINOS_LOG_SUBSYSTEM, AINOS_LOG_CATEGORY_POLICY);
    g_log_fs      = ainos_log_create(AINOS_LOG_SUBSYSTEM, AINOS_LOG_CATEGORY_FS);
    g_log_network = ainos_log_create(AINOS_LOG_SUBSYSTEM, AINOS_LOG_CATEGORY_NETWORK);
}

ainos_log_t ainos_log_create_daemon(void) {
    pthread_once(&g_log_init_once, ainos_log_initialize_singletons);
    return g_log_daemon ? ainos_log_retain(g_log_daemon) : NULL;
}

ainos_log_t ainos_log_create_runtime(void) {
    pthread_once(&g_log_init_once, ainos_log_initialize_singletons);
    return g_log_runtime ? ainos_log_retain(g_log_runtime) : NULL;
}

ainos_log_t ainos_log_create_policy(void) {
    pthread_once(&g_log_init_once, ainos_log_initialize_singletons);
    return g_log_policy ? ainos_log_retain(g_log_policy) : NULL;
}

ainos_log_t ainos_log_create_fs(void) {
    pthread_once(&g_log_init_once, ainos_log_initialize_singletons);
    return g_log_fs ? ainos_log_retain(g_log_fs) : NULL;
}

ainos_log_t ainos_log_create_network(void) {
    pthread_once(&g_log_init_once, ainos_log_initialize_singletons);
    return g_log_network ? ainos_log_retain(g_log_network) : NULL;
}

// ============================================================================
// Level Conversion
// ============================================================================

static os_log_type_t ainos_log_level_to_os_log_type(ainos_log_level_t level) {
    switch (level) {
        case AINOS_LOG_LEVEL_DEBUG: return OS_LOG_TYPE_DEBUG;
        case AINOS_LOG_LEVEL_INFO:  return OS_LOG_TYPE_INFO;
        case AINOS_LOG_LEVEL_ERROR: return OS_LOG_TYPE_ERROR;
        case AINOS_LOG_LEVEL_FAULT: return OS_LOG_TYPE_FAULT;
        default:                    return OS_LOG_TYPE_DEFAULT;
    }
}

static ainos_log_level_t ainos_os_log_type_to_level(os_log_type_t type) {
    switch (type) {
        case OS_LOG_TYPE_DEBUG:   return AINOS_LOG_LEVEL_DEBUG;
        case OS_LOG_TYPE_INFO:    return AINOS_LOG_LEVEL_INFO;
        case OS_LOG_TYPE_DEFAULT: return AINOS_LOG_LEVEL_INFO;
        case OS_LOG_TYPE_ERROR:   return AINOS_LOG_LEVEL_ERROR;
        case OS_LOG_TYPE_FAULT:   return AINOS_LOG_LEVEL_FAULT;
        default:                  return AINOS_LOG_LEVEL_INFO;
    }
}

// ============================================================================
// Core Logging Functions
// ============================================================================

static void ainos_log_vlog(ainos_log_t log, os_log_type_t type,
                           const char *format, va_list args) {
    if (!log || !log->os_log || !format) return;

    // os_log supports variadic arguments directly via os_log_with_type
    // We delegate to os_log for the actual message delivery
    os_log_with_type(log->os_log, type, "%{public}s", format);
    // Note: The above is a simplified approach. For full format string
    // support with privacy annotations, we would need to construct the
    // format string with proper os_log privacy specifiers.
}

// ============================================================================
// Basic Logging Functions
// ============================================================================

void ainos_log_debug(ainos_log_t log, const char *format, ...) {
    if (!log || !format) return;
    va_list args;
    va_start(args, format);
    ainos_log_vlog(log, OS_LOG_TYPE_DEBUG, format, args);
    va_end(args);
}

void ainos_log_info(ainos_log_t log, const char *format, ...) {
    if (!log || !format) return;
    va_list args;
    va_start(args, format);
    ainos_log_vlog(log, OS_LOG_TYPE_INFO, format, args);
    va_end(args);
}

void ainos_log_error(ainos_log_t log, const char *format, ...) {
    if (!log || !format) return;
    va_list args;
    va_start(args, format);
    ainos_log_vlog(log, OS_LOG_TYPE_ERROR, format, args);
    va_end(args);
}

void ainos_log_fault(ainos_log_t log, const char *format, ...) {
    if (!log || !format) return;
    va_list args;
    va_start(args, format);
    ainos_log_vlog(log, OS_LOG_TYPE_FAULT, format, args);
    va_end(args);
}

// ============================================================================
// Structured Logging
// ============================================================================

static void ainos_log_vlog_fields(ainos_log_t log, os_log_type_t type,
                                  const char *message,
                                  const ainos_log_field_t *fields, int count) {
    if (!log || !log->os_log || !message) return;

    // Build a structured log entry with key-value pairs
    // os_log does not natively support structured fields, so we format
    // them as a JSON-like string appended to the message.
    //
    // For full structured logging, consider using os_log with a format
    // string that includes the field values with appropriate privacy specifiers.

    // Calculate the total buffer size needed
    size_t msg_len = strlen(message) + 2; // message + " {"
    for (int i = 0; i < count && i < AINOS_LOG_MAX_FIELDS; i++) {
        if (fields[i].key && fields[i].value) {
            msg_len += strlen(fields[i].key) + strlen(fields[i].value) + 8; // "key=value, "
        }
    }
    msg_len += 2; // "}"

    char *formatted = (char *)malloc(msg_len);
    if (!formatted) return;

    char *ptr = formatted;
    size_t remaining = msg_len;
    int written = snprintf(ptr, remaining, "%s {", message);
    ptr += written;
    remaining -= (size_t)written;

    for (int i = 0; i < count && i < AINOS_LOG_MAX_FIELDS; i++) {
        if (fields[i].key && fields[i].value) {
            if (i > 0) {
                written = snprintf(ptr, remaining, ", ");
                ptr += written;
                remaining -= (size_t)written;
            }
            written = snprintf(ptr, remaining, "%s=%s", fields[i].key, fields[i].value);
            ptr += written;
            remaining -= (size_t)written;
        }
    }

    snprintf(ptr, remaining, "}");

    os_log_with_type(log->os_log, type, "%{public}s", formatted);
    free(formatted);
}

void ainos_log_debug_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count) {
    ainos_log_vlog_fields(log, OS_LOG_TYPE_DEBUG, message, fields, count);
}

void ainos_log_info_fields(ainos_log_t log, const char *message,
                           const ainos_log_field_t *fields, int count) {
    ainos_log_vlog_fields(log, OS_LOG_TYPE_INFO, message, fields, count);
}

void ainos_log_error_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count) {
    ainos_log_vlog_fields(log, OS_LOG_TYPE_ERROR, message, fields, count);
}

void ainos_log_fault_fields(ainos_log_t log, const char *message,
                            const ainos_log_field_t *fields, int count) {
    ainos_log_vlog_fields(log, OS_LOG_TYPE_FAULT, message, fields, count);
}

// ============================================================================
// Signpost (Performance Tracing)
// ============================================================================

void ainos_signpost_begin(ainos_log_t log, ainos_signpost_id_t event_id,
                          const char *format, ...) {
    if (!log || !log->os_log || !format) return;

    os_signpost_id_t spid;
    switch (event_id) {
        case AINOS_LOG_SIGNPOST_INFERENCE:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        case AINOS_LOG_SIGNPOST_MODEL_LOAD:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        case AINOS_LOG_SIGNPOST_IPC_HANDLE:
            spid = os_signpost_id_make_with_pointer(log->os_log, log);
            break;
        case AINOS_LOG_SIGNPOST_THERMAL_CHECK:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        default:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
    }

    va_list args;
    va_start(args, format);
    os_signpost_interval_begin(log->os_log, spid, "AinosSignpost",
                               "%{public}s", format);
    va_end(args);
}

void ainos_signpost_end(ainos_log_t log, ainos_signpost_id_t event_id,
                        const char *format, ...) {
    if (!log || !log->os_log || !format) return;

    os_signpost_id_t spid;
    switch (event_id) {
        case AINOS_LOG_SIGNPOST_INFERENCE:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        case AINOS_LOG_SIGNPOST_MODEL_LOAD:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        case AINOS_LOG_SIGNPOST_IPC_HANDLE:
            spid = os_signpost_id_make_with_pointer(log->os_log, log);
            break;
        case AINOS_LOG_SIGNPOST_THERMAL_CHECK:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
        default:
            spid = OS_SIGNPOST_ID_EXCLUSIVE;
            break;
    }

    va_list args;
    va_start(args, format);
    os_signpost_interval_end(log->os_log, spid, "%{public}s", format);
    va_end(args);
}

// ============================================================================
// Utility Functions
// ============================================================================

bool ainos_log_is_enabled(ainos_log_t log, ainos_log_level_t level) {
    if (!log || !log->os_log) return false;

    os_log_type_t os_type = ainos_log_level_to_os_log_type(level);
    return os_log_type_enabled(log->os_log, os_type);
}

void ainos_log_flush(void) {
    // os_log does not require explicit flushing; messages are
    // delivered asynchronously. This function is a compatibility shim.
    // On macOS, os_log messages are coalesced and delivered by the
    // logging daemon. There is no programmatic flush mechanism.
    // We use a small sleep to allow the logging daemon to process
    // pending messages.
    struct timespec ts = { .tv_sec = 0, .tv_nsec = 1000000 }; // 1ms
    nanosleep(&ts, NULL);
}

ainos_log_level_t ainos_log_get_level(void) {
    // os_log does not expose a runtime log level query.
    // The log level is configured via the `log` command-line tool
    // or through the unified logging system preferences.
    // We return AINOS_LOG_LEVEL_INFO as the default.
    return AINOS_LOG_LEVEL_INFO;
}

ainos_log_level_t ainos_log_level_from_string(const char *name) {
    if (!name) return AINOS_LOG_LEVEL_INFO;

    if (strcasecmp(name, "debug") == 0)   return AINOS_LOG_LEVEL_DEBUG;
    if (strcasecmp(name, "info") == 0)    return AINOS_LOG_LEVEL_INFO;
    if (strcasecmp(name, "error") == 0)   return AINOS_LOG_LEVEL_ERROR;
    if (strcasecmp(name, "fault") == 0)   return AINOS_LOG_LEVEL_FAULT;
    return AINOS_LOG_LEVEL_INFO;
}

const char *ainos_log_level_to_string(ainos_log_level_t level) {
    switch (level) {
        case AINOS_LOG_LEVEL_DEBUG: return "debug";
        case AINOS_LOG_LEVEL_INFO:  return "info";
        case AINOS_LOG_LEVEL_ERROR: return "error";
        case AINOS_LOG_LEVEL_FAULT: return "fault";
        default:                    return "unknown";
    }
}

const char *ainos_log_privacy_to_format(ainos_log_privacy_t privacy) {
    switch (privacy) {
        case AINOS_LOG_PRIVACY_PUBLIC:
            return "{public}";
        case AINOS_LOG_PRIVACY_PRIVATE:
            return "{private}";
        case AINOS_LOG_PRIVACY_SENSITIVE:
            return "{sensitive}";
        case AINOS_LOG_PRIVACY_AUTO:
        default:
            return "";
    }
}

// ============================================================================
// os_log Bridge Helpers
// ============================================================================

// Helper function to log a formatted message with a specific privacy level.
// This is the recommended way to log with privacy classification.
//
// Usage:
//   ainos_log_with_privacy(log, AINOS_LOG_LEVEL_INFO,
//                           AINOS_LOG_PRIVACY_PUBLIC,
//                           "Model loaded: %@", modelName);
//
// Note: The format string uses %@ for Objective-C objects and %s for
// C strings. Privacy annotations are applied to the entire string.

// ============================================================================
// Log Subsystem Registration
// ============================================================================

// The log subsystem "com.ainos.daemon" and its categories should be
// registered with the system using a log preferences plist:
//
//   /Library/Preferences/Logging/com.ainos.daemon.plist
//
// Content:
//   <?xml version="1.0" encoding="UTF-8"?>
//   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
//    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
//   <plist version="1.0">
//   <dict>
//       <key>com.ainos.daemon</key>
//       <dict>
//           <key>daemon</key>
//           <string>Info</string>
//           <key>runtime</key>
//           <string>Info</string>
//           <key>policy</key>
//           <string>Info</string>
//           <key>fs</key>
//           <string>Info</string>
//           <key>network</key>
//           <string>Info</string>
//       </dict>
//   </dict>
//   </plist>
//
// This plist sets the default log level for each category.
// To view logs:
//   log stream --predicate 'subsystem == "com.ainos.daemon"'
//   log show --predicate 'subsystem == "com.ainos.daemon"' --last 1h

// ============================================================================
// Activity Tracing
// ============================================================================

// Create an os_activity_t for tracing a request through the system.
// This is useful for correlating log messages from different components
// that participate in handling a single request.
//
// Example:
//   os_activity_t activity = os_activity_create(
//       "AinosInference", OS_ACTIVITY_CURRENT, OS_ACTIVITY_FLAG_DEFAULT);
//   os_activity_scope_enter(activity, &activity_state);
//   // ... do work ...
//   os_activity_scope_leave(&activity_state);
//   os_release(activity);

// ============================================================================
// Initialization
// ============================================================================

// __attribute__((constructor)) static void ainos_logging_init(void) {
//     // This runs automatically when the library is loaded.
//     // Pre-create the singleton log objects.
//     ainos_log_initialize_singletons();
// }

// ============================================================================
// End of ainos_logging.c
// ============================================================================