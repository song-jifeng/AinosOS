// Ainos OS - macOS XPC Service Implementation
// ============================================================================
//
// This file implements the XPC service for the Ainos AI daemon on macOS.
// It acts as a bridge between macOS XPC clients and the Ainos daemon's
// native IPC protocol (JSON-over-TCP).
//
// Architecture:
//   Client apps (e.g., AinosMenuBar, CLI tools) send XPC messages to
//   this service. The service translates them into the Ainos IPC protocol
//   (JSON lines over TCP to 127.0.0.1:9500) and returns the response.
//
// XPC Service Lifecycle:
//   1. launchd registers the service via MachServices in the plist
//   2. XPC connections are accepted by xpc_connection_set_event_handler
//   3. Each connection gets its own peer event handler loop
//   4. Messages are dispatched to the Ainos daemon via TCP
//
// Requirements:
//   - macOS 10.8+ (XPC was introduced in 10.8)
//   - Foundation and CoreFoundation frameworks
//   - Security framework for entitlement validation
//
// Compile with:
//   clang -x objective-c -fobjc-arc -framework Foundation \
//         -framework Security -o ainos_xpc_service ainos_xpc.c

#include <xpc/xpc.h>
#include <xpc/activity.h>
#include <Foundation/Foundation.h>
#include <Security/Security.h>
#include <CoreFoundation/CoreFoundation.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <pthread.h>
#include <signal.h>
#include <os/log.h>
#include <os/signpost.h>
#include <time.h>
#include <sys/stat.h>

// ============================================================================
// Constants
// ============================================================================

// Daemon IPC endpoint
#define AINOS_DAEMON_HOST       "127.0.0.1"
#define AINOS_DAEMON_PORT       9500
#define AINOS_DAEMON_SOCKET     "/var/run/ainos/ai-daemon.sock"
#define AINOS_IPC_TIMEOUT_SEC   30
#define AINOS_MAX_CONNECTIONS   128
#define AINOS_MAX_MSG_SIZE      (1024 * 1024)  // 1 MB max message
#define AINOS_BUF_SIZE          (64 * 1024)     // 64 KB read buffer

// XPC message types
#define AINOS_XPC_MSG_TYPE      "type"
#define AINOS_XPC_MSG_PAYLOAD   "payload"
#define AINOS_XPC_MSG_INFERENCE "inference"
#define AINOS_XPC_MSG_STATUS    "status"
#define AINOS_XPC_MSG_MODEL     "model"
#define AINOS_XPC_MSG_CONFIG    "config"
#define AINOS_XPC_MSG_THERMAL   "thermal"
#define AINOS_XPC_MSG_ERROR     "error"
#define AINOS_XPC_MSG_PING      "ping"
#define AINOS_XPC_MSG_SHUTDOWN  "shutdown"

// Entitlement for client authentication
#define AINOS_XPC_ENTITLEMENT   "com.ainos.daemon.xpc.client"

// Service identifier
#define AINOS_XPC_SERVICE_NAME  "com.ainos.daemon.xpc"

// Connection state
typedef enum {
    CONN_STATE_NEW = 0,
    CONN_STATE_ACTIVE,
    CONN_STATE_CLOSING,
    CONN_STATE_CLOSED,
} ainos_conn_state_t;

// ============================================================================
// Types
// ============================================================================

// Per-connection context
typedef struct ainos_conn_s {
    xpc_connection_t            peer;
    int                         daemon_fd;
    atomic_int                  state;
    pthread_mutex_t             write_lock;
    char                        client_id[64];
    uint64_t                    connect_time_ns;
    int                         ref_count;
    struct ainos_conn_s        *next;  // Linked list for connection tracking
} ainos_conn_t;

// Connection pool (simple linked list with mutex)
static pthread_mutex_t g_conn_list_lock = PTHREAD_MUTEX_INITIALIZER;
static ainos_conn_t   *g_conn_list = NULL;
static atomic_int      g_conn_count = 0;

// Daemon socket connection mutex (only one XPC -> daemon connection at a time)
static pthread_mutex_t g_daemon_lock = PTHREAD_MUTEX_INITIALIZER;
static int             g_daemon_fd = -1;

// Shutdown flag
static volatile sig_atomic_t g_shutdown = 0;

// Logging
static os_log_t g_xpc_log = NULL;

// ============================================================================
// Forward Declarations
// ============================================================================

static void ainos_conn_retain(ainos_conn_t *conn);
static void ainos_conn_release(ainos_conn_t *conn);
static void ainos_conn_close(ainos_conn_t *conn);
static void ainos_conn_handle_message(ainos_conn_t *conn, xpc_object_t event);
static int  ainos_daemon_connect(void);
static void ainos_daemon_disconnect(void);
static int  ainos_daemon_send(const char *json_msg, size_t len);
static char *ainos_daemon_recv(int fd, size_t *out_len);
static char *ainos_xpc_to_json(xpc_object_t xmsg);
static xpc_object_t ainos_json_to_xpc(const char *json, size_t len);
static bool ainos_validate_entitlement(xpc_connection_t peer);
static void ainos_conn_track_add(ainos_conn_t *conn);
static void ainos_conn_track_remove(ainos_conn_t *conn);
static void ainos_cleanup_idle_connections(void);

// ============================================================================
// Connection Tracking
// ============================================================================

static void ainos_conn_track_add(ainos_conn_t *conn) {
    pthread_mutex_lock(&g_conn_list_lock);
    conn->next = g_conn_list;
    g_conn_list = conn;
    atomic_fetch_add(&g_conn_count, 1);
    pthread_mutex_unlock(&g_conn_list_lock);
}

static void ainos_conn_track_remove(ainos_conn_t *conn) {
    pthread_mutex_lock(&g_conn_list_lock);
    ainos_conn_t **pp = &g_conn_list;
    while (*pp) {
        if (*pp == conn) {
            *pp = conn->next;
            conn->next = NULL;
            atomic_fetch_sub(&g_conn_count, 1);
            break;
        }
        pp = &(*pp)->next;
    }
    pthread_mutex_unlock(&g_conn_list_lock);
}

static void ainos_cleanup_idle_connections(void) {
    uint64_t now_ns = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    pthread_mutex_lock(&g_conn_list_lock);
    ainos_conn_t **pp = &g_conn_list;
    while (*pp) {
        ainos_conn_t *conn = *pp;
        int st = atomic_load(&conn->state);
        // Close connections that have been in CLOSING state for > 5 seconds
        if (st == CONN_STATE_CLOSING && (now_ns - conn->connect_time_ns) > 5ULL * NSEC_PER_SEC) {
            *pp = conn->next;
            conn->next = NULL;
            atomic_fetch_sub(&g_conn_count, 1);
            ainos_conn_close(conn);
            ainos_conn_release(conn);
            continue;
        }
        pp = &(*pp)->next;
    }
    pthread_mutex_unlock(&g_conn_list_lock);
}

// ============================================================================
// Connection Lifecycle
// ============================================================================

static ainos_conn_t *ainos_conn_create(xpc_connection_t peer) {
    ainos_conn_t *conn = (ainos_conn_t *)calloc(1, sizeof(ainos_conn_t));
    if (!conn) {
        os_log_error(g_xpc_log, "Failed to allocate connection context");
        return NULL;
    }

    conn->peer = peer;
    conn->daemon_fd = -1;
    conn->daemon_fd = ainos_daemon_connect();
    atomic_store(&conn->state, CONN_STATE_ACTIVE);
    conn->connect_time_ns = clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    conn->ref_count = 1;
    conn->next = NULL;

    // Generate a client ID from the peer audit token
    uuid_t auid;
    size_t auid_len = sizeof(auid);
    if (xpc_connection_get_audit_token(peer, auid, &auid_len)) {
        snprintf(conn->client_id, sizeof(conn->client_id),
                 "xpc-%02x%02x%02x%02x-%02x%02x%02x%02x",
                 auid[0], auid[1], auid[2], auid[3],
                 auid[4], auid[5], auid[6], auid[7]);
    } else {
        snprintf(conn->client_id, sizeof(conn->client_id), "xpc-unknown");
    }

    // Initialize mutex
    pthread_mutex_init(&conn->write_lock, NULL);

    // Track in the global list
    ainos_conn_track_add(conn);

    os_log_info(g_xpc_log, "Connection created: %{public}s", conn->client_id);
    return conn;
}

static void ainos_conn_retain(ainos_conn_t *conn) {
    if (conn) {
        atomic_fetch_add(&conn->ref_count, 1);
    }
}

static void ainos_conn_release(ainos_conn_t *conn) {
    if (!conn) return;
    if (atomic_fetch_sub(&conn->ref_count, 1) == 1) {
        // Last reference: clean up
        ainos_conn_track_remove(conn);
        pthread_mutex_destroy(&conn->write_lock);
        free(conn);
    }
}

static void ainos_conn_close(ainos_conn_t *conn) {
    if (!conn) return;

    int expected = CONN_STATE_ACTIVE;
    if (!atomic_compare_exchange_strong(&conn->state, &expected, CONN_STATE_CLOSING)) {
        return; // Already closing or closed
    }

    os_log_info(g_xpc_log, "Closing connection: %{public}s", conn->client_id);

    // Close the daemon socket
    pthread_mutex_lock(&conn->write_lock);
    if (conn->daemon_fd >= 0) {
        close(conn->daemon_fd);
        conn->daemon_fd = -1;
    }
    pthread_mutex_unlock(&conn->write_lock);

    // Cancel the XPC connection
    xpc_connection_cancel(conn->peer);

    atomic_store(&conn->state, CONN_STATE_CLOSED);
}

// ============================================================================
// Daemon IPC Connection
// ============================================================================

static int ainos_daemon_connect(void) {
    struct sockaddr_in addr;
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        os_log_error(g_xpc_log, "Failed to create TCP socket: %{darwin.errno}d", errno);
        return -1;
    }

    // Set socket timeout
    struct timeval tv = { .tv_sec = AINOS_IPC_TIMEOUT_SEC, .tv_usec = 0 };
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    // Enable TCP_NODELAY for low latency
    int flag = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &flag, sizeof(flag));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(AINOS_DAEMON_PORT);
    inet_pton(AF_INET, AINOS_DAEMON_HOST, &addr.sin_addr);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        os_log_error(g_xpc_log, "Failed to connect to daemon at %s:%d: %{darwin.errno}d",
                     AINOS_DAEMON_HOST, AINOS_DAEMON_PORT, errno);
        close(fd);
        return -1;
    }

    os_log_info(g_xpc_log, "Connected to daemon at %s:%d", AINOS_DAEMON_HOST, AINOS_DAEMON_PORT);
    return fd;
}

static void ainos_daemon_disconnect(void) {
    pthread_mutex_lock(&g_daemon_lock);
    if (g_daemon_fd >= 0) {
        close(g_daemon_fd);
        g_daemon_fd = -1;
    }
    pthread_mutex_unlock(&g_daemon_lock);
}

static int ainos_daemon_send(int fd, const char *json_msg, size_t len) {
    if (fd < 0 || !json_msg || len == 0) return -1;

    // Send the JSON message followed by a newline (NDJSON format)
    struct iovec iov[2];
    iov[0].iov_base = (void *)json_msg;
    iov[0].iov_len = len;
    char newline = '\n';
    iov[1].iov_base = &newline;
    iov[1].iov_len = 1;

    ssize_t written = 0;
    size_t total = len + 1;
    while (written < (ssize_t)total) {
        ssize_t n = writev(fd, iov + (written >= (ssize_t)len ? 1 : 0),
                           (written >= (ssize_t)len) ? 1 : 2);
        if (n < 0) {
            if (errno == EINTR) continue;
            os_log_error(g_xpc_log, "Daemon write error: %{darwin.errno}d", errno);
            return -1;
        }
        written += n;
    }

    return 0;
}

// Read a complete JSON line from the daemon.
// Returns a malloc'd buffer containing the response, or NULL on error.
// The caller must free the returned buffer.
static char *ainos_daemon_recv(int fd, size_t *out_len) {
    if (fd < 0) return NULL;

    size_t capacity = 4096;
    size_t length = 0;
    char *buffer = (char *)malloc(capacity);
    if (!buffer) return NULL;

    while (length < AINOS_MAX_MSG_SIZE) {
        if (length >= capacity - 1) {
            capacity *= 2;
            if (capacity > AINOS_MAX_MSG_SIZE + 1) capacity = AINOS_MAX_MSG_SIZE + 1;
            char *newbuf = (char *)realloc(buffer, capacity);
            if (!newbuf) {
                free(buffer);
                return NULL;
            }
            buffer = newbuf;
        }

        ssize_t n = read(fd, buffer + length, 1);
        if (n < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                // Timeout: return what we have so far
                break;
            }
            os_log_error(g_xpc_log, "Daemon read error: %{darwin.errno}d", errno);
            free(buffer);
            return NULL;
        }
        if (n == 0) {
            // EOF
            if (length == 0) {
                free(buffer);
                return NULL;
            }
            break;
        }

        length += n;

        // Check for newline (end of NDJSON message)
        if (buffer[length - 1] == '\n') {
            buffer[length - 1] = '\0';
            length--;
            break;
        }
    }

    buffer[length] = '\0';
    if (out_len) *out_len = length;
    return buffer;
}

// ============================================================================
// XPC Message Conversion
// ============================================================================

// Convert an XPC dictionary to a JSON string for the Ainos daemon.
// The daemon expects NDJSON with the same format as the IPC module.
static char *ainos_xpc_to_json(xpc_object_t xmsg) {
    if (xpc_get_type(xmsg) != XPC_TYPE_DICTIONARY) {
        return NULL;
    }

    const char *type = xpc_dictionary_get_string(xmsg, AINOS_XPC_MSG_TYPE);
    if (!type) {
        // Default to status if no type specified
        type = AINOS_XPC_MSG_STATUS;
    }

    xpc_object_t payload = xpc_dictionary_get_value(xmsg, AINOS_XPC_MSG_PAYLOAD);

    // Build JSON string based on message type
    if (strcmp(type, AINOS_XPC_MSG_PING) == 0) {
        return strdup("{\"type\":\"Status\"}");
    }

    if (strcmp(type, AINOS_XPC_MSG_STATUS) == 0) {
        return strdup("{\"type\":\"Status\"}");
    }

    if (strcmp(type, AINOS_XPC_MSG_INFERENCE) == 0) {
        // Extract inference parameters from payload
        const char *model = "default";
        const char *prompt = "";
        double temperature = 0.7;
        int64_t max_tokens = 1024;

        if (payload && xpc_get_type(payload) == XPC_TYPE_DICTIONARY) {
            const char *m = xpc_dictionary_get_string(payload, "model");
            if (m) model = m;
            const char *p = xpc_dictionary_get_string(payload, "prompt");
            if (p) prompt = p;
            if (xpc_dictionary_get_value(payload, "temperature")) {
                temperature = xpc_dictionary_get_double(payload, "temperature");
            }
            if (xpc_dictionary_get_value(payload, "max_tokens")) {
                max_tokens = xpc_dictionary_get_int64(payload, "max_tokens");
            }
        }

        // Escape JSON special characters in prompt
        // For simplicity, using a safe limited approach
        size_t prompt_len = strlen(prompt);
        size_t json_len = prompt_len + 512;
        char *json = (char *)malloc(json_len);
        if (!json) return NULL;

        // Simple JSON escaping
        char *escaped_prompt = (char *)malloc(prompt_len * 2 + 1);
        if (!escaped_prompt) { free(json); return NULL; }
        size_t j = 0;
        for (size_t i = 0; i < prompt_len; i++) {
            char c = prompt[i];
            if (c == '"' || c == '\\') {
                escaped_prompt[j++] = '\\';
            }
            escaped_prompt[j++] = c;
        }
        escaped_prompt[j] = '\0';

        snprintf(json, json_len,
                 "{\"type\":\"Inference\",\"model\":\"%s\",\"prompt\":\"%s\","
                 "\"temperature\":%.2f,\"max_tokens\":%lld}",
                 model, escaped_prompt, temperature, (long long)max_tokens);

        free(escaped_prompt);
        return json;
    }

    if (strcmp(type, AINOS_XPC_MSG_MODEL) == 0) {
        const char *action = "list";
        const char *model_path = "";

        if (payload && xpc_get_type(payload) == XPC_TYPE_DICTIONARY) {
            const char *a = xpc_dictionary_get_string(payload, "action");
            if (a) action = a;
            const char *p = xpc_dictionary_get_string(payload, "path");
            if (p) model_path = p;
        }

        if (strcmp(action, "load") == 0 && strlen(model_path) > 0) {
            size_t json_len = strlen(model_path) + 128;
            char *json = (char *)malloc(json_len);
            if (json) {
                snprintf(json, json_len,
                         "{\"type\":\"ModelLoad\",\"path\":\"%s\"}", model_path);
            }
            return json;
        } else if (strcmp(action, "unload") == 0 && strlen(model_path) > 0) {
            size_t json_len = strlen(model_path) + 128;
            char *json = (char *)malloc(json_len);
            if (json) {
                snprintf(json, json_len,
                         "{\"type\":\"ModelUnload\",\"model_id\":\"%s\"}", model_path);
            }
            return json;
        } else {
            return strdup("{\"type\":\"ModelList\"}");
        }
    }

    if (strcmp(type, AINOS_XPC_MSG_THERMAL) == 0) {
        return strdup("{\"type\":\"Status\"}");
    }

    if (strcmp(type, AINOS_XPC_MSG_CONFIG) == 0) {
        // Config requests are not yet implemented via IPC
        return strdup("{\"type\":\"Status\"}");
    }

    if (strcmp(type, AINOS_XPC_MSG_SHUTDOWN) == 0) {
        return strdup("{\"type\":\"Status\"}");
    }

    // Unknown type: treat as status
    return strdup("{\"type\":\"Status\"}");
}

// Convert a JSON response from the daemon to an XPC dictionary.
static xpc_object_t ainos_json_to_xpc(const char *json, size_t len) {
    if (!json || len == 0) {
        xpc_object_t resp = xpc_dictionary_create(NULL, NULL, 0);
        xpc_dictionary_set_string(resp, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
        xpc_dictionary_set_string(resp, "error", "Empty response from daemon");
        return resp;
    }

    __block xpc_object_t xresp = xpc_dictionary_create(NULL, NULL, 0);

    // Parse the JSON string using NSJSONSerialization
    @autoreleasepool {
        NSData *data = [NSData dataWithBytesNoCopy:(void *)json length:len freeWhenDone:NO];
        NSError *error = nil;
        id jsonObj = [NSJSONSerialization JSONObjectWithData:data
                                                     options:0
                                                       error:&error];
        if (error) {
            xpc_dictionary_set_string(xresp, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
            xpc_dictionary_set_string(xresp, "error",
                                      [[error localizedDescription] UTF8String]);
            return xresp;
        }

        if (![jsonObj isKindOfClass:[NSDictionary class]]) {
            xpc_dictionary_set_string(xresp, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
            xpc_dictionary_set_string(xresp, "error", "Invalid JSON response");
            return xresp;
        }

        NSDictionary *dict = (NSDictionary *)jsonObj;

        // Extract the type field
        NSString *typeStr = dict[@"type"];
        if (typeStr) {
            xpc_dictionary_set_string(xresp, AINOS_XPC_MSG_TYPE, [typeStr UTF8String]);
        }

        // Copy all string fields from the JSON to the XPC dictionary
        for (NSString *key in dict) {
            id value = dict[key];
            if ([value isKindOfClass:[NSString class]]) {
                xpc_dictionary_set_string(xresp, [key UTF8String], [value UTF8String]);
            } else if ([value isKindOfClass:[NSNumber class]]) {
                NSNumber *num = (NSNumber *)value;
                const char *objCType = [num objCType];
                if (strcmp(objCType, @encode(BOOL)) == 0 ||
                    strcmp(objCType, @encode(char)) == 0) {
                    xpc_dictionary_set_bool(xresp, [key UTF8String], [num boolValue]);
                } else if (strcmp(objCType, @encode(double)) == 0 ||
                           strcmp(objCType, @encode(float)) == 0) {
                    xpc_dictionary_set_double(xresp, [key UTF8String], [num doubleValue]);
                } else {
                    xpc_dictionary_set_int64(xresp, [key UTF8String], [num longLongValue]);
                }
            } else if ([value isKindOfClass:[NSArray class]]) {
                // Convert arrays to XPC arrays
                xpc_object_t xarr = xpc_array_create(NULL, 0);
                for (id item in (NSArray *)value) {
                    if ([item isKindOfClass:[NSString class]]) {
                        xpc_array_set_string(xarr, XPC_ARRAY_APPEND, [item UTF8String]);
                    } else if ([item isKindOfClass:[NSDictionary class]]) {
                        // Nested dicts are not fully converted in this simplified version
                        // but we include the key for forward compatibility
                    }
                }
                xpc_dictionary_set_value(xresp, [key UTF8String], xarr);
                xpc_release(xarr);
            } else if ([value isKindOfClass:[NSDictionary class]]) {
                // Nested dictionary: convert to XPC dict
                xpc_object_t xdict = xpc_dictionary_create(NULL, NULL, 0);
                for (NSString *nestedKey in (NSDictionary *)value) {
                    id nestedValue = ((NSDictionary *)value)[nestedKey];
                    if ([nestedValue isKindOfClass:[NSString class]]) {
                        xpc_dictionary_set_string(xdict, [nestedKey UTF8String],
                                                  [nestedValue UTF8String]);
                    } else if ([nestedValue isKindOfClass:[NSNumber class]]) {
                        xpc_dictionary_set_int64(xdict, [nestedKey UTF8String],
                                                 [nestedValue longLongValue]);
                    }
                }
                xpc_dictionary_set_value(xresp, [key UTF8String], xdict);
                xpc_release(xdict);
            }
        }
    }

    return xresp;
}

// ============================================================================
// Entitlement Validation
// ============================================================================

static bool ainos_validate_entitlement(xpc_connection_t peer) {
    // Get the audit token from the connection
    audit_token_t token = {0};
    size_t token_size = sizeof(token);

    // Note: xpc_connection_get_audit_token returns void, not bool
    // It always populates the buffer
    xpc_connection_get_audit_token(peer, &token, &token_size);

    // Create a SecTask from the audit token
    SecTaskRef task = SecTaskCreateWithAuditToken(NULL, token);
    if (!task) {
        os_log_error(g_xpc_log, "Failed to create SecTask from audit token");
        return false;
    }

    // Check for the required entitlement
    CFErrorRef error = NULL;
    CFStringRef entitlement = CFStringCreateWithCString(NULL,
        AINOS_XPC_ENTITLEMENT, kCFStringEncodingUTF8);

    Boolean hasEntitlement = SecTaskEvaluateForEntitlement(task, entitlement, &error);

    if (error) {
        os_log_error(g_xpc_log, "Entitlement check error: %{public}@", error);
        CFRelease(error);
    }

    CFRelease(entitlement);
    CFRelease(task);

    if (!hasEntitlement) {
        os_log_error(g_xpc_log, "Client lacks required entitlement: %s",
                     AINOS_XPC_ENTITLEMENT);
    }

    return (bool)hasEntitlement;
}

// ============================================================================
// XPC Event Handler
// ============================================================================

static void ainos_conn_handle_message(ainos_conn_t *conn, xpc_object_t event) {
    xpc_type_t type = xpc_get_type(event);

    if (type == XPC_TYPE_DICTIONARY) {
        // This is a message from the client
        os_signpost_id_t spid = os_signpost_id_make_with_pointer(g_xpc_log, conn);

        os_signpost_interval_begin(g_xpc_log, spid, "XPC_Handle", "Handle message from %s",
                                   conn->client_id);

        // Convert XPC message to JSON for the daemon
        char *json_msg = ainos_xpc_to_json(event);
        if (!json_msg) {
            // Send error response
            xpc_object_t reply = xpc_dictionary_create_reply(event);
            if (reply) {
                xpc_dictionary_set_string(reply, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
                xpc_dictionary_set_string(reply, "error", "Failed to convert message");
                xpc_connection_send_message(conn->peer, reply);
                xpc_release(reply);
            }
            os_signpost_interval_end(g_xpc_log, spid, "XPC_Handle");
            return;
        }

        size_t json_len = strlen(json_msg);
        os_log_debug(g_xpc_log, "Sending to daemon: %{public}s", json_msg);

        // Send to daemon and get response
        pthread_mutex_lock(&conn->write_lock);
        int fd = conn->daemon_fd;
        if (fd < 0) {
            // Try to reconnect
            fd = ainos_daemon_connect();
            conn->daemon_fd = fd;
        }

        char *response = NULL;
        size_t resp_len = 0;

        if (fd >= 0) {
            if (ainos_daemon_send(fd, json_msg, json_len) == 0) {
                response = ainos_daemon_recv(fd, &resp_len);
            }

            // Check for connection error
            if (!response) {
                os_log_error(g_xpc_log, "Daemon connection lost, reconnecting");
                close(fd);
                fd = ainos_daemon_connect();
                conn->daemon_fd = fd;
                if (fd >= 0) {
                    if (ainos_daemon_send(fd, json_msg, json_len) == 0) {
                        response = ainos_daemon_recv(fd, &resp_len);
                    }
                }
            }
        }
        pthread_mutex_unlock(&conn->write_lock);

        // Convert response to XPC and send back
        xpc_object_t reply = xpc_dictionary_create_reply(event);
        if (reply) {
            if (response) {
                xpc_object_t xresp = ainos_json_to_xpc(response, resp_len);
                // Copy all keys from xresp to reply
                xpc_dictionary_apply(xresp, ^bool(const char *key, xpc_object_t val) {
                    xpc_dictionary_set_value(reply, key, val);
                    return true;
                });
                xpc_release(xresp);
                free(response);
            } else {
                xpc_dictionary_set_string(reply, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
                xpc_dictionary_set_string(reply, "error",
                    "Daemon is not running. Start the Ainos daemon first.");
            }
            xpc_connection_send_message(conn->peer, reply);
            xpc_release(reply);
        }

        free(json_msg);
        os_signpost_interval_end(g_xpc_log, spid, "XPC_Handle");

    } else if (type == XPC_TYPE_ERROR) {
        // Connection error or interruption
        const char *desc = xpc_dictionary_get_string(event, XPC_ERROR_KEY_DESCRIPTION);
        if (event == XPC_ERROR_CONNECTION_INVALID) {
            os_log_info(g_xpc_log, "XPC connection invalidated: %s (%s)",
                        conn->client_id, desc ? desc : "unknown");
            ainos_conn_close(conn);
        } else if (event == XPC_ERROR_CONNECTION_INTERRUPTED) {
            os_log_info(g_xpc_log, "XPC connection interrupted: %s (%s)",
                        conn->client_id, desc ? desc : "unknown");
            // Connection will be re-established by launchd
        } else if (event == XPC_ERROR_TERMINATION_IMMINENT) {
            os_log_info(g_xpc_log, "XPC termination imminent");
            g_shutdown = 1;
        } else {
            os_log_info(g_xpc_log, "XPC error event: %s (type: %s)",
                        desc ? desc : "unknown", xpc_type_get_name(type));
        }
    }
}

// ============================================================================
// XPC Connection Event Handler
// ============================================================================

static void ainos_xpc_connection_handler(xpc_connection_t peer) {
    // Retain the peer connection
    xpc_retain(peer);

    // Set the connection's event handler
    xpc_connection_set_event_handler(peer, ^(xpc_object_t event) {
        // The connection event handler receives messages and lifecycle events
        // We need to find or create a connection context for this peer
        //
        // Note: In a real XPC service, the connection context is typically
        // attached via xpc_connection_set_context. For this implementation,
        // we use a dictionary keyed by the peer pointer.

        xpc_type_t type = xpc_get_type(event);

        if (type == XPC_TYPE_DICTIONARY) {
            // Check entitlement for this peer
            if (!ainos_validate_entitlement(peer)) {
                os_log_error(g_xpc_log, "Rejecting unauthorized XPC client");
                xpc_object_t reply = xpc_dictionary_create_reply(event);
                if (reply) {
                    xpc_dictionary_set_string(reply, AINOS_XPC_MSG_TYPE, AINOS_XPC_MSG_ERROR);
                    xpc_dictionary_set_string(reply, "error",
                        "Unauthorized: missing com.ainos.daemon.xpc.client entitlement");
                    xpc_connection_send_message(peer, reply);
                    xpc_release(reply);
                }
                return;
            }

            // Create a connection context for this peer
            ainos_conn_t *conn = ainos_conn_create(peer);
            if (conn) {
                ainos_conn_handle_message(conn, event);
                ainos_conn_release(conn);
            }
        } else if (type == XPC_TYPE_ERROR) {
            if (event == XPC_ERROR_CONNECTION_INVALID) {
                os_log_info(g_xpc_log, "Peer connection invalidated");
                xpc_release(peer);
            } else if (event == XPC_ERROR_CONNECTION_INTERRUPTED) {
                os_log_info(g_xpc_log, "Peer connection interrupted");
            }
        }
    });

    // Set the connection's name (for debugging)
    xpc_connection_set_name(peer, AINOS_XPC_SERVICE_NAME);

    // Resume the connection to start receiving events
    xpc_connection_resume(peer);
}

// ============================================================================
// Signal Handler
// ============================================================================

static void ainos_signal_handler(int sig) {
    g_shutdown = 1;
    os_log_info(g_xpc_log, "Received signal %d, initiating shutdown", sig);
}

// ============================================================================
// XPC Service Main
// ============================================================================

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        // Initialize logging
        g_xpc_log = os_log_create(AINOS_LOG_SUBSYSTEM, "xpc");
        os_log_info(g_xpc_log, "Ainos XPC Service starting (PID: %d)", getpid());

        // Set up signal handlers for graceful shutdown
        signal(SIGTERM, ainos_signal_handler);
        signal(SIGINT, ainos_signal_handler);
        signal(SIGQUIT, ainos_signal_handler);

        // Create the XPC service listener
        //
        // xpc_main will set up the service listener based on the MachServices
        // entry in the launchd plist. The connection handler is called for
        // each incoming connection.
        //
        // Note: xpc_main does not return. It runs the XPC event loop
        // until the service is terminated by launchd.
        xpc_main(ainos_xpc_connection_handler);

        // This code is never reached under normal circumstances
        os_log_info(g_xpc_log, "Ainos XPC Service shutting down");
        os_release(g_xpc_log);
    }

    return 0;
}

// ============================================================================
// XPC Service Bundle Info
// ============================================================================

// The XPC service bundle requires an Info.plist with:
//   - CFBundleIdentifier: com.ainos.daemon.xpc
//   - CFBundleName: Ainos XPC Service
//   - CFBundlePackageType: XPC!
//   - CFBundleShortVersionString: 1.0
//   - XPCService: { "ServiceType": "Application" }
//
// When built as a framework, the bundle structure is:
//   com.ainos.daemon.xpc/
//     Contents/
//       Info.plist
//       MacOS/
//         ainos_xpc_service
//       Resources/
//         (empty)
//
// The service is installed at:
//   /usr/local/lib/ainos/com.ainos.daemon.xpc/Contents/MacOS/ainos_xpc_service

// ============================================================================
// End of ainos_xpc.c
// ============================================================================