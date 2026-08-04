// AinosOS - D-Bus Server Implementation for AI Daemon
// Copyright (C) 2024 AinosOS Developers
//
// This program is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; either version 2 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// D-Bus interface for the AinosOS AI Daemon.
// Uses sd-bus (systemd's built-in D-Bus library) for bus integration.
//
// Compile:
//   gcc -std=c11 -c ainos_dbus.c -o ainos_dbus.o $(pkg-config --cflags libsystemd)
//   gcc ainos_dbus.o -o ainos_dbus $(pkg-config --libs libsystemd) -ljson-c
//
// Integration:
//   The daemon calls ainos_dbus_init() during startup, passing a callback
//   table for inference, model operations, and status queries.
//
// ============================================================================

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysinfo.h>
#include <time.h>
#include <unistd.h>

#include <systemd/sd-bus.h>
#include <systemd/sd-event.h>
#include <systemd/sd-daemon.h>

#ifdef HAVE_JSON_C
#include <json-c/json.h>
#include <json-c/json_object.h>
#include <json-c/json_tokener.h>
#endif

// ============================================================================
// Version and Interface Constants
// ============================================================================
#define AINOS_DBUS_VERSION          "1.0.0"
#define AINOS_DBUS_INTERFACE        "com.ainos.Daemon1"
#define AINOS_DBUS_OBJECT_PATH      "/com/ainos/Daemon1"
#define AINOS_DBUS_BUS_NAME         "com.ainos.Daemon1"
#define AINOS_DBUS_BUS_NAME_FALLBACK "com.ainos.Daemon1"
#define AINOS_DBUS_MAX_NAME_RETRIES  3
#define AINOS_DBUS_PROPERTY_CACHE_TTL_MS 1000

// ============================================================================
// Error Codes
// ============================================================================
#define AINOS_DBUS_ERR_SUCCESS       0
#define AINOS_DBUS_ERR_BUSY         -1
#define AINOS_DBUS_ERR_TIMEOUT      -2
#define AINOS_DBUS_ERR_INVALID_ARG  -3
#define AINOS_DBUS_ERR_NOT_FOUND    -4
#define AINOS_DBUS_ERR_INTERNAL     -5
#define AINOS_DBUS_ERR_PERMISSION   -6
#define AINOS_DBUS_ERR_UNAVAILABLE  -7

// ============================================================================
// Power Mode Constants (matches thermal.h)
// ============================================================================
#define AINOS_POWER_MODE_MAX        0
#define AINOS_POWER_MODE_BALANCED   1
#define AINOS_POWER_MODE_EFFICIENT  2
#define AINOS_POWER_MODE_EMERGENCY  3

// ============================================================================
// Forward Declarations
// ============================================================================
struct ainos_dbus_ctx;
typedef struct ainos_dbus_ctx ainos_dbus_ctx;

// ============================================================================
// Callback Types — Daemon implements these to bridge D-Bus to internal logic
// ============================================================================

/// Result of an asynchronous operation
typedef struct ainos_dbus_result {
    int   error_code;
    char *error_message;
    char *payload_json;  // JSON-encoded result data
} ainos_dbus_result;

/// Inference callback: perform AI inference
typedef ainos_dbus_result *(*ainos_infer_fn)(
    void      *user_data,
    const char *model,
    const char *prompt,
    double     temperature,
    uint32_t   max_tokens,
    const char *session_id);

/// Status callback: get daemon status
typedef ainos_dbus_result *(*ainos_status_fn)(
    void *user_data);

/// Model list callback: list available models
typedef ainos_dbus_result *(*ainos_model_list_fn)(
    void *user_data);

/// Model load callback: load a model from disk
typedef ainos_dbus_result *(*ainos_model_load_fn)(
    void       *user_data,
    const char *path);

/// Model unload callback: unload a model from memory
typedef ainos_dbus_result *(*ainos_model_unload_fn)(
    void       *user_data,
    const char *model_id);

/// Context store callback: store a key-value pair
typedef ainos_dbus_result *(*ainos_context_store_fn)(
    void       *user_data,
    const char *key,
    const char *value);

/// Context retrieve callback: retrieve a value by key
typedef ainos_dbus_result *(*ainos_context_retrieve_fn)(
    void       *user_data,
    const char *key);

/// Thermal snapshot callback: get current thermal state
typedef ainos_dbus_result *(*ainos_thermal_snapshot_fn)(
    void *user_data);

/// Property getter callback for arbitrary properties
typedef ainos_dbus_result *(*ainos_property_get_fn)(
    void       *user_data,
    const char *property_name);

/// Property setter callback
typedef ainos_dbus_result *(*ainos_property_set_fn)(
    void       *user_data,
    const char *property_name,
    const char *value);

/// Daemon callback table — all functions are optional (may be NULL)
typedef struct ainos_dbus_callbacks {
    void                       *user_data;
    ainos_infer_fn              infer;
    ainos_status_fn             status;
    ainos_model_list_fn         model_list;
    ainos_model_load_fn         model_load;
    ainos_model_unload_fn       model_unload;
    ainos_context_store_fn      context_store;
    ainos_context_retrieve_fn   context_retrieve;
    ainos_thermal_snapshot_fn   thermal_snapshot;
    ainos_property_get_fn       property_get;
    ainos_property_set_fn       property_set;
} ainos_dbus_callbacks;

// ============================================================================
// Helpers: JSON payload construction
// ============================================================================

#ifdef HAVE_JSON_C
static inline json_object *ainos_dbus_json_error(int code, const char *fmt, ...)
{
    va_list ap;
    char buf[1024];
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);

    json_object *obj = json_object_new_object();
    json_object_object_add(obj, "error_code", json_object_new_int(code));
    json_object_object_add(obj, "error_message", json_object_new_string(buf));
    return obj;
}

static inline json_object *ainos_dbus_json_success(void)
{
    json_object *obj = json_object_new_object();
    json_object_object_add(obj, "status", json_object_new_string("ok"));
    return obj;
}
#endif

// ============================================================================
// D-Bus Context Structure
// ============================================================================

struct ainos_dbus_ctx {
    sd_bus               *bus;              // D-Bus connection (system bus)
    sd_event             *event;            // Event loop (shared with daemon)
    ainos_dbus_callbacks  callbacks;        // Daemon callback table
    char                  version[64];      // Version string
    char                 *bus_name;         // Acquired bus name
    int                   name_retries;     // Bus name acquisition retries
    bool                  initialized;      // Whether init completed
    bool                  running;          // Whether event loop is active
    uint64_t              start_time_ms;    // Monotonic start time
    char                  daemon_status[32];// "running"/"loading"/"error"/etc.
    char                  log_level[16];    // Current log level

    // Property cache (simple, TTL-based)
    struct {
        uint64_t     last_update_ms;
        char         version[64];
        char         status[32];
        uint64_t     uptime_sec;
    } property_cache;

    // Signal emission throttle
    struct {
        uint64_t     last_thermal_ms;
        uint64_t     last_error_ms;
        uint64_t     min_interval_ms;  // Minimum gap between same signal type
    } signal_throttle;
};

// ============================================================================
// Static Helpers
// ============================================================================

static uint64_t monotonic_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

static uint64_t now_sec(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec;
}

static bool is_valid_utf8(const char *s)
{
    if (!s) return false;
    int codepoint, state = 0;
    for (; *s; ++s) {
        unsigned char c = (unsigned char)*s;
        if (state == 0) {
            if (c < 0x80) continue;
            if (c >= 0xC2 && c <= 0xDF) { state = 1; codepoint = c & 0x1F; continue; }
            if (c >= 0xE0 && c <= 0xEF) { state = 2; codepoint = c & 0x0F; continue; }
            if (c >= 0xF0 && c <= 0xF4) { state = 3; codepoint = c & 0x07; continue; }
            return false;
        }
        if (c < 0x80 || c > 0xBF) return false;
        codepoint = (codepoint << 6) | (c & 0x3F);
        --state;
    }
    return state == 0;
}

static char *ainos_strdup(const char *s)
{
    if (!s) return NULL;
    size_t len = strlen(s);
    char *copy = (char *)malloc(len + 1);
    if (!copy) return NULL;
    memcpy(copy, s, len + 1);
    return copy;
}

// ============================================================================
// Result Helpers
// ============================================================================

static ainos_dbus_result *ainos_dbus_result_ok(const char *json_payload)
{
    ainos_dbus_result *r = (ainos_dbus_result *)calloc(1, sizeof(*r));
    if (!r) return NULL;
    r->error_code = 0;
    if (json_payload)
        r->payload_json = ainos_strdup(json_payload);
    return r;
}

static ainos_dbus_result *ainos_dbus_result_err(int code, const char *fmt, ...)
{
    ainos_dbus_result *r = (ainos_dbus_result *)calloc(1, sizeof(*r));
    if (!r) return NULL;
    r->error_code = code;
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    r->error_message = ainos_strdup(buf);
    char json_buf[2048];
    snprintf(json_buf, sizeof(json_buf),
             "{\"error_code\":%d,\"error_message\":\"%s\"}",
             code, buf);
    r->payload_json = ainos_strdup(json_buf);
    return r;
}

static void ainos_dbus_result_free(ainos_dbus_result *r)
{
    if (!r) return;
    free(r->error_message);
    free(r->payload_json);
    free(r);
}

// ============================================================================
// D-Bus Reply Helpers
// ============================================================================

static int reply_simple_string(sd_bus_message *reply, const char *value)
{
    return sd_bus_message_append(reply, "s", value ? value : "");
}

static int reply_string_and_bool(sd_bus_message *reply, const char *str, int b)
{
    int r = sd_bus_message_append(reply, "sb", str ? str : "", b != 0);
    return r;
}

// ============================================================================
// Method Handlers
// ============================================================================

// --------------------------------------------------------------------------
// Infer method handler
// --------------------------------------------------------------------------
static int method_infer(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *model = NULL, *prompt = NULL, *session_id = "";
    double temperature = 0.7;
    uint32_t max_tokens = 512;

    int r = sd_bus_message_read(msg, "ssdus", &model, &prompt, &temperature, &max_tokens, &session_id);
    if (r < 0) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.InvalidArgs", "Invalid arguments");
        return r;
    }

    if (!ctx->callbacks.infer) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.Unavailable",
                               "Inference not available (no callback registered)");
        return -EOPNOTSUPP;
    }

    ainos_dbus_result *result = ctx->callbacks.infer(
        ctx->callbacks.user_data, model, prompt, temperature, max_tokens, session_id);

    if (!result || result->error_code != 0) {
        int code = result ? result->error_code : AINOS_DBUS_ERR_INTERNAL;
        const char *msg_text = result ? result->error_message : "Internal error";
        sd_bus_error_setf(ret_error, "com.ainos.Daemon1.Error.InferenceFailed",
                          "Inference failed: %s", msg_text);
        ainos_dbus_result_free(result);
        return -EIO;
    }

    // Parse result JSON for output, tokens, ms, source
    // For now, use the result payload as-is or extract fields
    sd_bus_message *reply = NULL;
    r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) { ainos_dbus_result_free(result); return r; }

    // Append output, tokens_generated, inference_ms, source
    // If payload contains JSON, try to parse it; otherwise use the payload as output
    const char *output = result->payload_json ? result->payload_json : "";
    uint32_t tokens = 0;
    uint64_t ms = 0;
    const char *source = "local";

#ifdef HAVE_JSON_C
    if (result->payload_json) {
        json_object *jobj = json_tokener_parse(result->payload_json);
        if (jobj) {
            json_object *jout = NULL, *jtok = NULL, *jms = NULL, *jsrc = NULL;
            if (json_object_object_get_ex(jobj, "output", &jout))
                output = json_object_get_string(jout);
            if (json_object_object_get_ex(jobj, "tokens_generated", &jtok))
                tokens = (uint32_t)json_object_get_int64(jtok);
            if (json_object_object_get_ex(jobj, "inference_ms", &jms))
                ms = (uint64_t)json_object_get_int64(jms);
            if (json_object_object_get_ex(jobj, "source", &jsrc))
                source = json_object_get_string(jsrc);
            json_object_put(jobj);
        }
    }
#endif

    r = sd_bus_message_append(reply, "suts", output, tokens, ms, source);
    if (r >= 0)
        r = sd_bus_send(NULL, reply, NULL);

    sd_bus_message_unref(reply);
    ainos_dbus_result_free(result);
    return r;
}

// --------------------------------------------------------------------------
// Status method handler
// --------------------------------------------------------------------------
static int method_status(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;

    // Default values
    const char *version = ctx->version;
    uint64_t uptime = (monotonic_ms() - ctx->start_time_ms) / 1000;
    uint32_t models_loaded = 0;
    uint64_t total_requests = 0;
    int network_available = 0;
    uint32_t active_sessions = 0;
    double cpu_temp = 0.0;
    uint32_t power_mode = AINOS_POWER_MODE_MAX;

    if (ctx->callbacks.status) {
        ainos_dbus_result *result = ctx->callbacks.status(ctx->callbacks.user_data);
        if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
            json_object *jobj = json_tokener_parse(result->payload_json);
            if (jobj) {
                json_object *jv = NULL;
                if (json_object_object_get_ex(jobj, "uptime", &jv))
                    uptime = (uint64_t)json_object_get_int64(jv);
                if (json_object_object_get_ex(jobj, "models_loaded", &jv))
                    models_loaded = (uint32_t)json_object_get_int64(jv);
                if (json_object_object_get_ex(jobj, "total_requests", &jv))
                    total_requests = (uint64_t)json_object_get_int64(jv);
                if (json_object_object_get_ex(jobj, "network_available", &jv))
                    network_available = json_object_get_boolean(jv);
                if (json_object_object_get_ex(jobj, "active_sessions", &jv))
                    active_sessions = (uint32_t)json_object_get_int64(jv);
                if (json_object_object_get_ex(jobj, "cpu_temp", &jv))
                    cpu_temp = json_object_get_double(jv);
                if (json_object_object_get_ex(jobj, "power_mode", &jv))
                    power_mode = (uint32_t)json_object_get_int64(jv);
                json_object_put(jobj);
            }
#endif
        }
        ainos_dbus_result_free(result);
    }

    sd_bus_message *reply = NULL;
    int r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) return r;

    r = sd_bus_message_append(reply, "stutbudu",
                              version,
                              uptime,
                              models_loaded,
                              total_requests,
                              (int)network_available,
                              active_sessions,
                              cpu_temp,
                              power_mode);
    if (r >= 0)
        r = sd_bus_send(NULL, reply, NULL);

    sd_bus_message_unref(reply);
    return r;
}

// --------------------------------------------------------------------------
// ModelList method handler
// --------------------------------------------------------------------------
static int method_model_list(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *models_json = "[]";

    if (ctx->callbacks.model_list) {
        ainos_dbus_result *result = ctx->callbacks.model_list(ctx->callbacks.user_data);
        if (result && result->error_code == 0 && result->payload_json)
            models_json = result->payload_json;
        ainos_dbus_result_free(result);
    }

    return reply_simple_string(sd_bus_message_new_method_return(msg, NULL), models_json);
    // Note: above returns the new message pointer; we need proper handling:
    // Actually let's do this properly:
}

// Redo ModelList properly
static int method_model_list_v2(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *models_json = "[]";

    if (ctx->callbacks.model_list) {
        ainos_dbus_result *result = ctx->callbacks.model_list(ctx->callbacks.user_data);
        if (result && result->error_code == 0 && result->payload_json)
            models_json = result->payload_json;
        ainos_dbus_result_free(result);
    }

    sd_bus_message *reply = NULL;
    int r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) return r;
    r = sd_bus_message_append(reply, "s", models_json);
    if (r >= 0) r = sd_bus_send(NULL, reply, NULL);
    sd_bus_message_unref(reply);
    return r;
}

// --------------------------------------------------------------------------
// ModelLoad method handler
// --------------------------------------------------------------------------
static int method_model_load(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *path = NULL;

    int r = sd_bus_message_read(msg, "s", &path);
    if (r < 0 || !path) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.InvalidArgs",
                               "Model path is required");
        return r < 0 ? r : -EINVAL;
    }

    if (!ctx->callbacks.model_load) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.Unavailable",
                               "Model load not available");
        return -EOPNOTSUPP;
    }

    ainos_dbus_result *result = ctx->callbacks.model_load(ctx->callbacks.user_data, path);
    if (!result || result->error_code != 0) {
        int code = result ? result->error_code : AINOS_DBUS_ERR_INTERNAL;
        const char *msg_str = result ? result->error_message : "Internal error";
        sd_bus_error_setf(ret_error, "com.ainos.Daemon1.Error.ModelLoadFailed",
                          "Model load failed: %s", msg_str);
        ainos_dbus_result_free(result);
        return -EIO;
    }

    // Parse result for model_id, status, message
    const char *model_id = "";
    const char *status = "loaded";
    const char *message = "Model loaded successfully";

#ifdef HAVE_JSON_C
    if (result->payload_json) {
        json_object *jobj = json_tokener_parse(result->payload_json);
        if (jobj) {
            json_object *jf = NULL;
            if (json_object_object_get_ex(jobj, "model_id", &jf))
                model_id = json_object_get_string(jf);
            if (json_object_object_get_ex(jobj, "status", &jf))
                status = json_object_get_string(jf);
            if (json_object_object_get_ex(jobj, "message", &jf))
                message = json_object_get_string(jf);
            json_object_put(jobj);
        }
    }
#endif

    // Emit ModelLoaded signal
    ainos_dbus_emit_model_loaded(ctx, model_id, "", 0);

    sd_bus_message *reply = NULL;
    r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) { ainos_dbus_result_free(result); return r; }
    r = sd_bus_message_append(reply, "sss", model_id, status, message);
    if (r >= 0) r = sd_bus_send(NULL, reply, NULL);
    sd_bus_message_unref(reply);
    ainos_dbus_result_free(result);
    return r;
}

// --------------------------------------------------------------------------
// ModelUnload method handler
// --------------------------------------------------------------------------
static int method_model_unload(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *model_id = NULL;

    int r = sd_bus_message_read(msg, "s", &model_id);
    if (r < 0 || !model_id) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.InvalidArgs",
                               "Model ID is required");
        return r < 0 ? r : -EINVAL;
    }

    if (!ctx->callbacks.model_unload) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.Unavailable",
                               "Model unload not available");
        return -EOPNOTSUPP;
    }

    ainos_dbus_result *result = ctx->callbacks.model_unload(ctx->callbacks.user_data, model_id);
    if (!result || result->error_code != 0) {
        int code = result ? result->error_code : AINOS_DBUS_ERR_INTERNAL;
        const char *msg_str = result ? result->error_message : "Internal error";
        sd_bus_error_setf(ret_error, "com.ainos.Daemon1.Error.ModelUnloadFailed",
                          "Model unload failed: %s", msg_str);
        ainos_dbus_result_free(result);
        return -EIO;
    }

    const char *status = "unloaded";
    const char *message = "Model unloaded successfully";

#ifdef HAVE_JSON_C
    if (result->payload_json) {
        json_object *jobj = json_tokener_parse(result->payload_json);
        if (jobj) {
            json_object *jf = NULL;
            if (json_object_object_get_ex(jobj, "status", &jf))
                status = json_object_get_string(jf);
            if (json_object_object_get_ex(jobj, "message", &jf))
                message = json_object_get_string(jf);
            json_object_put(jobj);
        }
    }
#endif

    // Emit ModelUnloaded signal
    ainos_dbus_emit_model_unloaded(ctx, model_id);

    sd_bus_message *reply = NULL;
    r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) { ainos_dbus_result_free(result); return r; }
    r = sd_bus_message_append(reply, "ss", status, message);
    if (r >= 0) r = sd_bus_send(NULL, reply, NULL);
    sd_bus_message_unref(reply);
    ainos_dbus_result_free(result);
    return r;
}

// --------------------------------------------------------------------------
// ContextStore method handler
// --------------------------------------------------------------------------
static int method_context_store(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *key = NULL, *value = NULL;

    int r = sd_bus_message_read(msg, "ss", &key, &value);
    if (r < 0 || !key || !value) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.InvalidArgs",
                               "Key and value are required");
        return r < 0 ? r : -EINVAL;
    }

    if (!ctx->callbacks.context_store) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.Unavailable",
                               "Context store not available");
        return -EOPNOTSUPP;
    }

    ainos_dbus_result *result = ctx->callbacks.context_store(ctx->callbacks.user_data, key, value);
    int stored = (result && result->error_code == 0) ? 1 : 0;
    ainos_dbus_result_free(result);

    sd_bus_message *reply = NULL;
    r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) return r;
    r = sd_bus_message_append(reply, "b", stored);
    if (r >= 0) r = sd_bus_send(NULL, reply, NULL);
    sd_bus_message_unref(reply);
    return r;
}

// --------------------------------------------------------------------------
// ContextRetrieve method handler
// --------------------------------------------------------------------------
static int method_context_retrieve(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    const char *key = NULL;

    int r = sd_bus_message_read(msg, "s", &key);
    if (r < 0 || !key) {
        sd_bus_error_set_const(ret_error, "com.ainos.Daemon1.Error.InvalidArgs",
                               "Key is required");
        return r < 0 ? r : -EINVAL;
    }

    const char *value = "";
    int found = 0;

    if (ctx->callbacks.context_retrieve) {
        ainos_dbus_result *result = ctx->callbacks.context_retrieve(ctx->callbacks.user_data, key);
        if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
            json_object *jobj = json_tokener_parse(result->payload_json);
            if (jobj) {
                json_object *jv = NULL;
                if (json_object_object_get_ex(jobj, "value", &jv))
                    value = json_object_get_string(jv);
                if (json_object_object_get_ex(jobj, "found", &jv))
                    found = json_object_get_boolean(jv);
                json_object_put(jobj);
            }
#endif
        }
        ainos_dbus_result_free(result);
    }

    sd_bus_message *reply = NULL;
    r = sd_bus_message_new_method_return(msg, &reply);
    if (r < 0) return r;
    r = sd_bus_message_append(reply, "sb", value, found);
    if (r >= 0) r = sd_bus_send(NULL, reply, NULL);
    sd_bus_message_unref(reply);
    return r;
}

// ============================================================================
// Property Getter/Setter
// ============================================================================

static int property_get(sd_bus *bus, const char *path, const char *interface,
                        const char *property, sd_bus_message *reply,
                        void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;

    if (strcmp(property, "Version") == 0) {
        return sd_bus_message_append(reply, "s", ctx->version);
    }
    if (strcmp(property, "Status") == 0) {
        return sd_bus_message_append(reply, "s", ctx->daemon_status);
    }
    if (strcmp(property, "Uptime") == 0) {
        uint64_t uptime = (monotonic_ms() - ctx->start_time_ms) / 1000;
        return sd_bus_message_append(reply, "t", uptime);
    }
    if (strcmp(property, "LogLevel") == 0) {
        return sd_bus_message_append(reply, "s", ctx->log_level);
    }
    if (strcmp(property, "CpuTemperature") == 0) {
        double temp = 0.0;
        if (ctx->callbacks.thermal_snapshot) {
            ainos_dbus_result *result = ctx->callbacks.thermal_snapshot(ctx->callbacks.user_data);
            if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
                json_object *jobj = json_tokener_parse(result->payload_json);
                if (jobj) {
                    json_object *jt = NULL;
                    if (json_object_object_get_ex(jobj, "cpu_temp_celsius", &jt))
                        temp = json_object_get_double(jt);
                    json_object_put(jobj);
                }
#endif
            }
            ainos_dbus_result_free(result);
        }
        return sd_bus_message_append(reply, "d", temp);
    }
    if (strcmp(property, "PowerMode") == 0) {
        uint32_t mode = AINOS_POWER_MODE_MAX;
        if (ctx->callbacks.thermal_snapshot) {
            ainos_dbus_result *result = ctx->callbacks.thermal_snapshot(ctx->callbacks.user_data);
            if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
                json_object *jobj = json_tokener_parse(result->payload_json);
                if (jobj) {
                    json_object *jm = NULL;
                    if (json_object_object_get_ex(jobj, "power_mode", &jm))
                        mode = (uint32_t)json_object_get_int64(jm);
                    json_object_put(jobj);
                }
#endif
            }
            ainos_dbus_result_free(result);
        }
        return sd_bus_message_append(reply, "u", mode);
    }
    if (strcmp(property, "MemoryUsed") == 0) {
        // Read memory from /proc/self/status
        uint64_t mem = 0;
        FILE *f = fopen("/proc/self/status", "r");
        if (f) {
            char line[256];
            while (fgets(line, sizeof(line), f)) {
                if (sscanf(line, "VmRSS: %" SCNu64 " kB", &mem) == 1)
                    break;
            }
            fclose(f);
        }
        return sd_bus_message_append(reply, "t", mem * 1024);
    }
    if (strcmp(property, "ModelsLoaded") == 0) {
        uint32_t count = 0;
        if (ctx->callbacks.status) {
            ainos_dbus_result *result = ctx->callbacks.status(ctx->callbacks.user_data);
            if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
                json_object *jobj = json_tokener_parse(result->payload_json);
                if (jobj) {
                    json_object *jm = NULL;
                    if (json_object_object_get_ex(jobj, "models_loaded", &jm))
                        count = (uint32_t)json_object_get_int64(jm);
                    json_object_put(jobj);
                }
#endif
            }
            ainos_dbus_result_free(result);
        }
        return sd_bus_message_append(reply, "u", count);
    }

    // Try custom property getter
    if (ctx->callbacks.property_get) {
        ainos_dbus_result *result = ctx->callbacks.property_get(ctx->callbacks.user_data, property);
        if (result && result->error_code == 0 && result->payload_json) {
#ifdef HAVE_JSON_C
            json_object *jobj = json_tokener_parse(result->payload_json);
            if (jobj) {
                json_object *jv = NULL;
                if (json_object_object_get_ex(jobj, "value", &jv)) {
                    const char *val = json_object_get_string(jv);
                    int r = sd_bus_message_append(reply, "v", "s", val);
                    json_object_put(jobj);
                    ainos_dbus_result_free(result);
                    return r;
                }
                json_object_put(jobj);
            }
#endif
        }
        ainos_dbus_result_free(result);
    }

    return sd_bus_error_setf(ret_error, SD_BUS_ERROR_UNKNOWN_PROPERTY,
                             "Unknown property: %s", property);
}

static int property_set(sd_bus *bus, const char *path, const char *interface,
                        const char *property, sd_bus_message *value,
                        void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;

    if (strcmp(property, "LogLevel") == 0) {
        const char *s = NULL;
        int r = sd_bus_message_read(value, "s", &s);
        if (r < 0 || !s) {
            return sd_bus_error_set_const(ret_error, SD_BUS_ERROR_INVALID_ARGS,
                                          "LogLevel must be a string");
        }
        if (strcmp(s, "trace") != 0 && strcmp(s, "debug") != 0 &&
            strcmp(s, "info") != 0 && strcmp(s, "warn") != 0 &&
            strcmp(s, "error") != 0) {
            return sd_bus_error_setf(ret_error, SD_BUS_ERROR_INVALID_ARGS,
                                     "Invalid log level: %s", s);
        }
        strncpy(ctx->log_level, s, sizeof(ctx->log_level) - 1);
        return 0;
    }

    // Try custom property setter
    if (ctx->callbacks.property_set) {
        const char *val = NULL;
        // Read the variant
        // For simplicity, we expect a string variant
        sd_bus_message *m = value;
        const char *contents = sd_bus_message_get_signature(m, true);
        if (contents && strcmp(contents, "s") == 0) {
            int r = sd_bus_message_read(m, "s", &val);
            if (r >= 0 && val) {
                ainos_dbus_result *result = ctx->callbacks.property_set(
                    ctx->callbacks.user_data, property, val);
                int ok = (result && result->error_code == 0);
                ainos_dbus_result_free(result);
                if (ok) return 0;
            }
        }
    }

    return sd_bus_error_setf(ret_error, SD_BUS_ERROR_UNKNOWN_PROPERTY,
                             "Cannot set property: %s", property);
}

// ============================================================================
// Signal Emission Functions
// ============================================================================

int ainos_dbus_emit_thermal_event(ainos_dbus_ctx *ctx, double cpu_temp,
                                   uint32_t zone, uint32_t power_mode)
{
    if (!ctx || !ctx->bus || !ctx->running) return -EINVAL;

    // Throttle: don't emit more than once per 2 seconds
    uint64_t now = monotonic_ms();
    if (now - ctx->signal_throttle.last_thermal_ms < ctx->signal_throttle.min_interval_ms)
        return 0;
    ctx->signal_throttle.last_thermal_ms = now;

    sd_bus_message *m = NULL;
    int r = sd_bus_message_new_signal(ctx->bus, &m,
                                       AINOS_DBUS_OBJECT_PATH,
                                       AINOS_DBUS_INTERFACE,
                                       "ThermalEvent");
    if (r < 0) return r;

    r = sd_bus_message_append(m, "duu", cpu_temp, zone, power_mode);
    if (r >= 0)
        r = sd_bus_send(ctx->bus, m, NULL);

    sd_bus_message_unref(m);
    return r;
}

int ainos_dbus_emit_model_loaded(ainos_dbus_ctx *ctx, const char *model_id,
                                  const char *model_name, uint64_t size_mb)
{
    if (!ctx || !ctx->bus || !ctx->running) return -EINVAL;

    sd_bus_message *m = NULL;
    int r = sd_bus_message_new_signal(ctx->bus, &m,
                                       AINOS_DBUS_OBJECT_PATH,
                                       AINOS_DBUS_INTERFACE,
                                       "ModelLoaded");
    if (r < 0) return r;

    r = sd_bus_message_append(m, "sst", model_id ? model_id : "",
                              model_name ? model_name : "", size_mb);
    if (r >= 0)
        r = sd_bus_send(ctx->bus, m, NULL);

    sd_bus_message_unref(m);
    return r;
}

int ainos_dbus_emit_model_unloaded(ainos_dbus_ctx *ctx, const char *model_id)
{
    if (!ctx || !ctx->bus || !ctx->running) return -EINVAL;

    sd_bus_message *m = NULL;
    int r = sd_bus_message_new_signal(ctx->bus, &m,
                                       AINOS_DBUS_OBJECT_PATH,
                                       AINOS_DBUS_INTERFACE,
                                       "ModelUnloaded");
    if (r < 0) return r;

    r = sd_bus_message_append(m, "s", model_id ? model_id : "");
    if (r >= 0)
        r = sd_bus_send(ctx->bus, m, NULL);

    sd_bus_message_unref(m);
    return r;
}

int ainos_dbus_emit_error(ainos_dbus_ctx *ctx, int error_code,
                           const char *error_message, const char *error_domain)
{
    if (!ctx || !ctx->bus || !ctx->running) return -EINVAL;

    // Throttle: don't emit more than once per 5 seconds
    uint64_t now = monotonic_ms();
    if (now - ctx->signal_throttle.last_error_ms < 5000)
        return 0;
    ctx->signal_throttle.last_error_ms = now;

    sd_bus_message *m = NULL;
    int r = sd_bus_message_new_signal(ctx->bus, &m,
                                       AINOS_DBUS_OBJECT_PATH,
                                       AINOS_DBUS_INTERFACE,
                                       "Error");
    if (r < 0) return r;

    r = sd_bus_message_append(m, "iss",
                              error_code,
                              error_message ? error_message : "",
                              error_domain ? error_domain : "");
    if (r >= 0)
        r = sd_bus_send(ctx->bus, m, NULL);

    sd_bus_message_unref(m);
    return r;
}

// ============================================================================
// Bus Name Acquisition
// ============================================================================

static int on_bus_name_lost(sd_bus_message *msg, void *userdata, sd_bus_error *ret_error)
{
    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)userdata;
    fprintf(stderr, "[ainos-dbus] Lost bus name '%s', attempting re-acquisition...\n",
            ctx->bus_name);

    if (ctx->name_retries < AINOS_DBUS_MAX_NAME_RETRIES) {
        ctx->name_retries++;
        int r = sd_bus_request_name_async(ctx->bus, NULL,
                                           AINOS_DBUS_BUS_NAME, 0);
        if (r < 0)
            fprintf(stderr, "[ainos-dbus] Failed to re-request bus name: %s\n",
                    strerror(-r));
    } else {
        fprintf(stderr, "[ainos-dbus] Max retries reached for bus name '%s'\n",
                ctx->bus_name);
    }
    return 0;
}

static int acquire_bus_name(ainos_dbus_ctx *ctx)
{
    int r = sd_bus_request_name_async(ctx->bus, NULL, AINOS_DBUS_BUS_NAME, 0);
    if (r < 0) {
        // Try alternate name
        char alt_name[128];
        snprintf(alt_name, sizeof(alt_name), "%s.%d",
                 AINOS_DBUS_BUS_NAME_FALLBACK, (int)now_sec());
        r = sd_bus_request_name_async(ctx->bus, NULL, alt_name, 0);
        if (r < 0) {
            fprintf(stderr, "[ainos-dbus] Failed to acquire bus name '%s': %s\n",
                    alt_name, strerror(-r));
            return r;
        }
        ctx->bus_name = ainos_strdup(alt_name);
    } else {
        ctx->bus_name = ainos_strdup(AINOS_DBUS_BUS_NAME);
    }

    // Add match for name loss signal
    sd_bus_match_signal(ctx->bus, NULL, "org.freedesktop.DBus",
                        "/org/freedesktop/DBus",
                        "org.freedesktop.DBus",
                        "NameLost",
                        on_bus_name_lost, ctx);

    fprintf(stdout, "[ainos-dbus] Acquired bus name: %s\n", ctx->bus_name);
    return 0;
}

// ============================================================================
// vtable: D-Bus method table
// ============================================================================

static const sd_bus_vtable ainos_dbus_vtable[] = {
    SD_BUS_VTABLE_START(0),

    // ---- Methods ----
    SD_BUS_METHOD("Infer",           "ssdus", "suts",  method_infer,               SD_BUS_VTABLE_UNPRIVILEGED),
    SD_BUS_METHOD("Status",          "",       "sttutbudu", method_status,          SD_BUS_VTABLE_UNPRIVILEGED),
    SD_BUS_METHOD("ModelList",       "",       "s",     method_model_list_v2,      SD_BUS_VTABLE_UNPRIVILEGED),
    SD_BUS_METHOD("ModelLoad",       "s",      "sss",   method_model_load,         0),
    SD_BUS_METHOD("ModelUnload",     "s",      "ss",    method_model_unload,       0),
    SD_BUS_METHOD("ContextStore",    "ss",     "b",     method_context_store,      SD_BUS_VTABLE_UNPRIVILEGED),
    SD_BUS_METHOD("ContextRetrieve", "s",      "sb",    method_context_retrieve,   SD_BUS_VTABLE_UNPRIVILEGED),

    // ---- Signals ----
    SD_BUS_SIGNAL("ThermalEvent",   "duu"),
    SD_BUS_SIGNAL("ModelLoaded",    "sst"),
    SD_BUS_SIGNAL("ModelUnloaded",  "s"),
    SD_BUS_SIGNAL("Error",          "iss"),

    // ---- Properties ----
    SD_BUS_PROPERTY("Version",         "s", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("Status",          "s", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("Uptime",          "t", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("LogLevel",        "s", property_get, property_set, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("CpuTemperature",  "d", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("PowerMode",       "u", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("MemoryUsed",      "t", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),
    SD_BUS_PROPERTY("ModelsLoaded",    "u", property_get, 0, SD_BUS_VTABLE_PROPERTY_EMITS_CHANGE),

    SD_BUS_VTABLE_END
};

// ============================================================================
// Initialization
// ============================================================================

ainos_dbus_ctx *ainos_dbus_init(ainos_dbus_callbacks *callbacks,
                                 sd_event *event_loop)
{
    if (!callbacks) {
        fprintf(stderr, "[ainos-dbus] ERROR: callbacks table is NULL\n");
        return NULL;
    }

    ainos_dbus_ctx *ctx = (ainos_dbus_ctx *)calloc(1, sizeof(*ctx));
    if (!ctx) {
        fprintf(stderr, "[ainos-dbus] ERROR: Out of memory\n");
        return NULL;
    }

    ctx->start_time_ms = monotonic_ms();
    strncpy(ctx->version, AINOS_DBUS_VERSION, sizeof(ctx->version) - 1);
    strncpy(ctx->daemon_status, "starting", sizeof(ctx->daemon_status) - 1);
    strncpy(ctx->log_level, "info", sizeof(ctx->log_level) - 1);
    ctx->signal_throttle.min_interval_ms = 2000;
    ctx->name_retries = 0;
    memcpy(&ctx->callbacks, callbacks, sizeof(*callbacks));

    // Use provided event loop, or create a new one
    if (event_loop) {
        ctx->event = event_loop;
        sd_event_ref(ctx->event);
    } else {
        int r = sd_event_default(&ctx->event);
        if (r < 0) {
            fprintf(stderr, "[ainos-dbus] Failed to create event loop: %s\n",
                    strerror(-r));
            goto fail;
        }
    }

    // Open system bus connection
    int r = sd_bus_open_system(&ctx->bus);
    if (r < 0) {
        // Try user bus as fallback
        fprintf(stderr, "[ainos-dbus] System bus unavailable (%s), trying user bus...\n",
                strerror(-r));
        r = sd_bus_open_user(&ctx->bus);
        if (r < 0) {
            fprintf(stderr, "[ainos-dbus] Failed to open D-Bus: %s\n",
                    strerror(-r));
            goto fail;
        }
    }

    // Attach bus to event loop
    r = sd_bus_attach_event(ctx->bus, ctx->event, 0);
    if (r < 0) {
        fprintf(stderr, "[ainos-dbus] Failed to attach bus to event loop: %s\n",
                strerror(-r));
        goto fail;
    }

    // Add the D-Bus object vtable
    r = sd_bus_add_object_vtable(ctx->bus, NULL,
                                  AINOS_DBUS_OBJECT_PATH,
                                  AINOS_DBUS_INTERFACE,
                                  ainos_dbus_vtable,
                                  ctx);
    if (r < 0) {
        fprintf(stderr, "[ainos-dbus] Failed to add object vtable: %s\n",
                strerror(-r));
        goto fail;
    }

    // Acquire bus name
    r = acquire_bus_name(ctx);
    if (r < 0) {
        fprintf(stderr, "[ainos-dbus] Warning: continuing without bus name\n");
        // Not fatal — we can still respond to method calls
    }

    // Notify systemd that we're ready
    sd_notify(0, "READY=1\nSTATUS=D-Bus interface ready\n");

    ctx->initialized = true;
    strncpy(ctx->daemon_status, "running", sizeof(ctx->daemon_status) - 1);

    fprintf(stdout, "[ainos-dbus] Initialized: interface=%s, path=%s, bus=%s\n",
            AINOS_DBUS_INTERFACE, AINOS_DBUS_OBJECT_PATH,
            ctx->bus_name ? ctx->bus_name : "(anonymous)");

    return ctx;

fail:
    if (ctx->bus) {
        sd_bus_detach_event(ctx->bus, 0);
        sd_bus_unref(ctx->bus);
    }
    if (ctx->event) sd_event_unref(ctx->event);
    free(ctx->bus_name);
    free(ctx);
    return NULL;
}

// ============================================================================
// Event Loop Integration
// ============================================================================

int ainos_dbus_run(ainos_dbus_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return -EINVAL;

    ctx->running = true;
    fprintf(stdout, "[ainos-dbus] Event loop running\n");

    int r = sd_event_loop(ctx->event);
    if (r < 0) {
        fprintf(stderr, "[ainos-dbus] Event loop exited with error: %s\n",
                strerror(-r));
    }

    ctx->running = false;
    return r;
}

int ainos_dbus_run_once(ainos_dbus_ctx *ctx, uint64_t timeout_ms)
{
    if (!ctx || !ctx->initialized || !ctx->running) return -EINVAL;

    uint64_t usec = timeout_ms > 0 ? timeout_ms * 1000 : UINT64_MAX;
    return sd_event_run(ctx->event, usec);
}

void ainos_dbus_stop(ainos_dbus_ctx *ctx)
{
    if (!ctx || !ctx->running) return;
    ctx->running = false;
    sd_event_exit(ctx->event, 0);
}

// ============================================================================
// Shutdown
// ============================================================================

void ainos_dbus_shutdown(ainos_dbus_ctx *ctx)
{
    if (!ctx) return;

    ctx->running = false;
    strncpy(ctx->daemon_status, "shutting_down", sizeof(ctx->daemon_status) - 1);

    if (ctx->bus_name) {
        sd_bus_release_name(ctx->bus, ctx->bus_name);
        fprintf(stdout, "[ainos-dbus] Released bus name: %s\n", ctx->bus_name);
    }

    if (ctx->bus) {
        sd_bus_detach_event(ctx->bus, 0);
        sd_bus_flush(ctx->bus);
        sd_bus_close(ctx->bus);
        sd_bus_unref(ctx->bus);
        ctx->bus = NULL;
    }

    if (ctx->event) {
        sd_event_unref(ctx->event);
        ctx->event = NULL;
    }

    free(ctx->bus_name);
    ctx->bus_name = NULL;
    ctx->initialized = false;

    sd_notify(0, "STOPPING=1\nSTATUS=D-Bus interface shut down\n");

    fprintf(stdout, "[ainos-dbus] Shutdown complete\n");
    free(ctx);
}

// ============================================================================
// Utility Functions
// ============================================================================

int ainos_dbus_set_status(ainos_dbus_ctx *ctx, const char *status)
{
    if (!ctx || !status) return -EINVAL;
    strncpy(ctx->daemon_status, status, sizeof(ctx->daemon_status) - 1);

    // Emit PropertiesChanged signal
    sd_bus_emit_properties_changed(ctx->bus, AINOS_DBUS_OBJECT_PATH,
                                    AINOS_DBUS_INTERFACE,
                                    "Status", NULL);
    return 0;
}

int ainos_dbus_set_log_level(ainos_dbus_ctx *ctx, const char *level)
{
    if (!ctx || !level) return -EINVAL;
    strncpy(ctx->log_level, level, sizeof(ctx->log_level) - 1);

    sd_bus_emit_properties_changed(ctx->bus, AINOS_DBUS_OBJECT_PATH,
                                    AINOS_DBUS_INTERFACE,
                                    "LogLevel", NULL);
    return 0;
}

const char *ainos_dbus_get_bus_name(ainos_dbus_ctx *ctx)
{
    return ctx ? ctx->bus_name : NULL;
}

bool ainos_dbus_is_running(ainos_dbus_ctx *ctx)
{
    return ctx && ctx->initialized && ctx->running;
}