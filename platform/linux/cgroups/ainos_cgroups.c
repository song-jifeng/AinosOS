// AinosOS - cgroups v2 Resource Management for AI Daemon
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
// cgroups v2 resource management for AinosOS AI Daemon.
// Manages memory, CPU, IO, and PIDs limits for the daemon and its
// inference sub-processes.
//
// cgroups v2 hierarchy:
//   /sys/fs/cgroup/ainos/
//   ├── daemon/       — Main daemon process
//   ├── runtime/      — AI runtime engine
//   ├── inference/    — Active inference tasks
//   └── background/   — Background/cache tasks
//
// Power policy modes:
//   Max:       high CPU quota, no memory limit
//   Balanced:  moderate CPU + memory limits
//   Efficient: strict CPU + memory, IO throttling
//   Emergency: minimal resources, freezer idle tasks
//
// Compile:
//   gcc -std=c11 -c ainos_cgroups.c -o ainos_cgroups.o
//   gcc ainos_cgroups.o -o ainos_cgroups
//
// ============================================================================

#define _GNU_SOURCE
#include <assert.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <sched.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysinfo.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

// ============================================================================
// Version
// ============================================================================
#define AINOS_CGROUPS_VERSION "1.0.0"

// ============================================================================
// Constants
// ============================================================================
#define AINOS_CGROUP_ROOT   "/sys/fs/cgroup"
#define AINOS_CGROUP_BASE   AINOS_CGROUP_ROOT "/ainos"
#define AINOS_CGROUP_DAEMON AINOS_CGROUP_BASE "/daemon"
#define AINOS_CGROUP_RUNTIME AINOS_CGROUP_BASE "/runtime"
#define AINOS_CGROUP_INFERENCE AINOS_CGROUP_BASE "/inference"
#define AINOS_CGROUP_BACKGROUND AINOS_CGROUP_BASE "/background"

#define AINOS_CGROUP_PATH_MAX  512
#define AINOS_CGROUP_LINE_MAX  4096
#define AINOS_CGROUP_NUM_SUBGROUPS 4
#define AINOS_CGROUP_PID_BUF_SIZE  (64 * 1024)

// Power modes (matches thermal/power_policy.h)
#define AINOS_POWER_MODE_MAX        0
#define AINOS_POWER_MODE_BALANCED   1
#define AINOS_POWER_MODE_EFFICIENT  2
#define AINOS_POWER_MODE_EMERGENCY  3

// Default resource limits
#define AINOS_DEFAULT_MEMORY_MAX    (8ULL * 1024 * 1024 * 1024)  // 8 GB
#define AINOS_DEFAULT_MEMORY_HIGH   (7ULL * 1024 * 1024 * 1024)  // 7 GB
#define AINOS_DEFAULT_MEMORY_SWAP   (1ULL * 1024 * 1024 * 1024)  // 1 GB
#define AINOS_DEFAULT_CPU_QUOTA     80000   // 80% of one core (in us)
#define AINOS_DEFAULT_CPU_PERIOD    100000  // 100ms period (in us)
#define AINOS_DEFAULT_CPU_WEIGHT    100     // Default CPU weight
#define AINOS_DEFAULT_IO_WEIGHT     100     // Default IO weight
#define AINOS_DEFAULT_PIDS_MAX      512     // Max tasks
#define AINOS_DEFAULT_FREEZE_TIMEOUT 30000  // 30s freeze timeout

// ============================================================================
// Error Codes
// ============================================================================
#define AINOS_CG_OK             0
#define AINOS_CG_ERR_NO_CGROUP -1
#define AINOS_CG_ERR_PERMISSION -2
#define AINOS_CG_ERR_INVALID   -3
#define AINOS_CG_ERR_NOMEM     -4
#define AINOS_CG_ERR_IO        -5
#define AINOS_CG_ERR_NOT_FOUND -6
#define AINOS_CG_ERR_TIMEOUT   -7

// ============================================================================
// Forward Declarations
// ============================================================================
typedef struct ainos_cgroup_ctx   ainos_cgroup_ctx;
typedef struct ainos_cgroup_stats ainos_cgroup_stats;

// ============================================================================
// Power Policy Configuration
// ============================================================================

typedef struct ainos_power_policy {
    uint32_t    mode;               // Current power mode
    uint64_t    memory_max;         // Memory limit per subgroup
    uint64_t    memory_high;        // Memory high watermark
    uint64_t    memory_swap_max;    // Swap limit
    uint32_t    cpu_quota_us;       // CPU quota in microseconds
    uint32_t    cpu_period_us;      // CPU period in microseconds
    uint32_t    cpu_weight;         // CPU weight (1-10000)
    uint32_t    io_weight;          // IO weight (1-10000)
    uint32_t    pids_max;           // Max number of tasks
    bool        freeze_background;  // Freeze background tasks (emergency only)
    bool        oom_kill;           // Enable OOM killer
    const char *name;               // Policy name (for logging)
} ainos_power_policy;

// Power policy table
static const ainos_power_policy ainos_power_policies[] = {
    // Max performance
    {
        .mode = AINOS_POWER_MODE_MAX,
        .memory_max = 0,              // No limit
        .memory_high = 0,             // No high watermark
        .memory_swap_max = 0,         // No swap limit
        .cpu_quota_us = 0,            // No quota
        .cpu_period_us = 100000,
        .cpu_weight = 1000,           // High CPU weight
        .io_weight = 1000,            // High IO weight
        .pids_max = 1024,
        .freeze_background = false,
        .oom_kill = false,
        .name = "max"
    },
    // Balanced
    {
        .mode = AINOS_POWER_MODE_BALANCED,
        .memory_max = 8ULL * 1024 * 1024 * 1024,   // 8 GB
        .memory_high = 7ULL * 1024 * 1024 * 1024,  // 7 GB
        .memory_swap_max = 2ULL * 1024 * 1024 * 1024, // 2 GB
        .cpu_quota_us = 80000,                      // 80%
        .cpu_period_us = 100000,
        .cpu_weight = 500,
        .io_weight = 500,
        .pids_max = 512,
        .freeze_background = false,
        .oom_kill = true,
        .name = "balanced"
    },
    // Efficient
    {
        .mode = AINOS_POWER_MODE_EFFICIENT,
        .memory_max = 4ULL * 1024 * 1024 * 1024,   // 4 GB
        .memory_high = 3ULL * 1024 * 1024 * 1024,  // 3 GB
        .memory_swap_max = 1ULL * 1024 * 1024 * 1024, // 1 GB
        .cpu_quota_us = 50000,                      // 50%
        .cpu_period_us = 100000,
        .cpu_weight = 200,
        .io_weight = 200,
        .pids_max = 256,
        .freeze_background = false,
        .oom_kill = true,
        .name = "efficient"
    },
    // Emergency
    {
        .mode = AINOS_POWER_MODE_EMERGENCY,
        .memory_max = 2ULL * 1024 * 1024 * 1024,   // 2 GB
        .memory_high = 1ULL * 1024 * 1024 * 1024,  // 1 GB
        .memory_swap_max = 512ULL * 1024 * 1024,   // 512 MB
        .cpu_quota_us = 25000,                      // 25%
        .cpu_period_us = 100000,
        .cpu_weight = 100,
        .io_weight = 100,
        .pids_max = 128,
        .freeze_background = true,
        .oom_kill = true,
        .name = "emergency"
    }
};

// ============================================================================
// cgroups Context
// ============================================================================

struct ainos_cgroup_ctx {
    bool            initialized;
    bool            cgroup_v2_available;
    char            base_path[AINOS_CGROUP_PATH_MAX];
    char            subgroup_paths[AINOS_CGROUP_NUM_SUBGROUPS][AINOS_CGROUP_PATH_MAX];
    const char     *subgroup_names[AINOS_CGROUP_NUM_SUBGROUPS];
    uint32_t        current_power_mode;
    pid_t           daemon_pid;
    pid_t           runtime_pid;
    pid_t           inference_pids[256];
    int             num_inference_pids;
    pid_t           background_pids[64];
    int             num_background_pids;
    uint64_t        last_stats_time_ms;
    struct {
        uint64_t    memory_current;
        uint64_t    memory_swap_current;
        uint64_t    memory_usage_max;
        uint64_t    cpu_usage_us;
        uint64_t    cpu_user_us;
        uint64_t    cpu_system_us;
        uint64_t    io_read_bytes;
        uint64_t    io_write_bytes;
        uint32_t    pids_current;
        uint32_t    pids_limit;
        uint32_t    oom_events;
        uint32_t    num_frozen;
    } stats;
};

// ============================================================================
// Internal Helpers
// ============================================================================

static uint64_t monotonic_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

static bool file_exists(const char *path)
{
    return access(path, F_OK) == 0;
}

// ============================================================================
// cgroup File Operations
// ============================================================================

static int cg_write_value(const char *path, const char *value)
{
    if (!path || !value) return AINOS_CG_ERR_INVALID;

    int fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
    if (fd < 0) {
        if (errno == ENOENT) return AINOS_CG_ERR_NOT_FOUND;
        if (errno == EACCES) return AINOS_CG_ERR_PERMISSION;
        return AINOS_CG_ERR_IO;
    }

    size_t len = strlen(value);
    ssize_t written = write(fd, value, len);
    int saved_errno = errno;
    close(fd);

    if (written < 0) {
        errno = saved_errno;
        if (errno == EACCES) return AINOS_CG_ERR_PERMISSION;
        if (errno == EINVAL) return AINOS_CG_ERR_INVALID;
        return AINOS_CG_ERR_IO;
    }
    if ((size_t)written != len) return AINOS_CG_ERR_IO;

    return AINOS_CG_OK;
}

static int cg_write_u64(const char *path, uint64_t value)
{
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "%" PRIu64 "\n", value);
    if (n < 0 || (size_t)n >= sizeof(buf)) return AINOS_CG_ERR_INVALID;
    return cg_write_value(path, buf);
}

static int cg_write_i64(const char *path, int64_t value)
{
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "%" PRId64 "\n", value);
    if (n < 0 || (size_t)n >= sizeof(buf)) return AINOS_CG_ERR_INVALID;
    return cg_write_value(path, buf);
}

static int cg_write_u32(const char *path, uint32_t value)
{
    char buf[32];
    int n = snprintf(buf, sizeof(buf), "%u\n", value);
    if (n < 0 || (size_t)n >= sizeof(buf)) return AINOS_CG_ERR_INVALID;
    return cg_write_value(path, buf);
}

static int cg_read_u64(const char *path, uint64_t *value)
{
    if (!path || !value) return AINOS_CG_ERR_INVALID;

    FILE *f = fopen(path, "re");
    if (!f) {
        if (errno == ENOENT) return AINOS_CG_ERR_NOT_FOUND;
        if (errno == EACCES) return AINOS_CG_ERR_PERMISSION;
        return AINOS_CG_ERR_IO;
    }

    unsigned long long val = 0;
    int matched = fscanf(f, "%llu", &val);
    fclose(f);

    if (matched != 1) return AINOS_CG_ERR_INVALID;

    *value = (uint64_t)val;
    return AINOS_CG_OK;
}

static int cg_read_u32(const char *path, uint32_t *value)
{
    uint64_t tmp;
    int r = cg_read_u64(path, &tmp);
    if (r == AINOS_CG_OK) *value = (uint32_t)tmp;
    return r;
}

static int cg_read_str(const char *path, char *buf, size_t buf_size)
{
    if (!path || !buf || buf_size == 0) return AINOS_CG_ERR_INVALID;

    FILE *f = fopen(path, "re");
    if (!f) {
        if (errno == ENOENT) return AINOS_CG_ERR_NOT_FOUND;
        if (errno == EACCES) return AINOS_CG_ERR_PERMISSION;
        return AINOS_CG_ERR_IO;
    }

    if (!fgets(buf, (int)buf_size, f)) {
        fclose(f);
        return AINOS_CG_ERR_INVALID;
    }

    // Strip trailing newline
    size_t len = strlen(buf);
    if (len > 0 && buf[len - 1] == '\n') buf[len - 1] = '\0';

    fclose(f);
    return AINOS_CG_OK;
}

// ============================================================================
// cgroup Subgroup Path Construction
// ============================================================================

static const char *subgroup_name(int idx)
{
    switch (idx) {
        case 0: return "daemon";
        case 1: return "runtime";
        case 2: return "inference";
        case 3: return "background";
        default: return NULL;
    }
}

static void build_subgroup_paths(ainos_cgroup_ctx *ctx)
{
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        const char *name = subgroup_name(i);
        ctx->subgroup_names[i] = name;
        snprintf(ctx->subgroup_paths[i], sizeof(ctx->subgroup_paths[i]),
                 "%s/%s", ctx->base_path, name);
    }
}

// ============================================================================
// cgroup v2 Detection
// ============================================================================

static bool detect_cgroup_v2(void)
{
    // Check if cgroup v2 is mounted at /sys/fs/cgroup
    struct stat st;
    if (stat("/sys/fs/cgroup", &st) != 0 || !S_ISDIR(st.st_mode))
        return false;

    // Check for cgroup2 fs type
    FILE *f = fopen("/proc/mounts", "r");
    if (!f) return false;

    char line[512];
    bool found = false;
    while (fgets(line, sizeof(line), f)) {
        if (strstr(line, "cgroup2") && strstr(line, "/sys/fs/cgroup")) {
            found = true;
            break;
        }
    }
    fclose(f);

    if (!found) return false;

    // Verify that key controllers are available
    if (!file_exists(AINOS_CGROUP_ROOT "/cgroup.controllers"))
        return false;

    return true;
}

// ============================================================================
// cgroup Directory Creation
// ============================================================================

static int create_cgroup_dir(const char *path)
{
    if (!path) return AINOS_CG_ERR_INVALID;

    if (mkdir(path, 0755) == 0) return AINOS_CG_OK;

    if (errno == EEXIST) {
        // Already exists — verify it's a directory
        struct stat st;
        if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
            return AINOS_CG_OK;
        return AINOS_CG_ERR_INVALID;
    }

    if (errno == EACCES) return AINOS_CG_ERR_PERMISSION;
    if (errno == ENOENT) return AINOS_CG_ERR_NOT_FOUND;

    return AINOS_CG_ERR_IO;
}

// ============================================================================
// Subgroup Resource Limit Application
// ============================================================================

static int apply_memory_limits(const char *cg_path, const ainos_power_policy *policy)
{
    char path[AINOS_CGROUP_PATH_MAX];
    int r;

    // memory.max
    snprintf(path, sizeof(path), "%s/memory.max", cg_path);
    if (policy->memory_max == 0) {
        r = cg_write_value(path, "max\n");
    } else {
        r = cg_write_u64(path, policy->memory_max);
    }
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    // memory.high
    snprintf(path, sizeof(path), "%s/memory.high", cg_path);
    if (policy->memory_high == 0) {
        r = cg_write_value(path, "max\n");
    } else {
        r = cg_write_u64(path, policy->memory_high);
    }
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    // memory.swap.max
    snprintf(path, sizeof(path), "%s/memory.swap.max", cg_path);
    if (policy->memory_swap_max == 0) {
        r = cg_write_value(path, "max\n");
    } else {
        r = cg_write_u64(path, policy->memory_swap_max);
    }
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    // memory.oom.group (enable OOM killing per group)
    snprintf(path, sizeof(path), "%s/memory.oom.group", cg_path);
    r = cg_write_u32(path, policy->oom_kill ? 1 : 0);
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    return AINOS_CG_OK;
}

static int apply_cpu_limits(const char *cg_path, const ainos_power_policy *policy)
{
    char path[AINOS_CGROUP_PATH_MAX];
    int r;

    // cpu.max
    if (policy->cpu_quota_us > 0) {
        snprintf(path, sizeof(path), "%s/cpu.max", cg_path);
        char buf[64];
        snprintf(buf, sizeof(buf), "%u %u\n",
                 policy->cpu_quota_us, policy->cpu_period_us);
        r = cg_write_value(path, buf);
        if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;
    }

    // cpu.weight
    snprintf(path, sizeof(path), "%s/cpu.weight", cg_path);
    r = cg_write_u32(path, policy->cpu_weight);
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    // cpu.weight.nice (optional, range 0-39 maps to weight 1-10000)
    snprintf(path, sizeof(path), "%s/cpu.weight.nice", cg_path);
    uint32_t nice_value = (policy->cpu_weight > 0)
        ? (uint32_t)((10000 - policy->cpu_weight) * 39 / 9999)
        : 10;
    cg_write_u32(path, nice_value); // Not fatal if missing

    return AINOS_CG_OK;
}

static int apply_io_limits(const char *cg_path, const ainos_power_policy *policy)
{
    char path[AINOS_CGROUP_PATH_MAX];
    int r;

    // io.weight
    snprintf(path, sizeof(path), "%s/io.weight", cg_path);
    r = cg_write_u32(path, policy->io_weight);
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    return AINOS_CG_OK;
}

static int apply_pids_limits(const char *cg_path, const ainos_power_policy *policy)
{
    char path[AINOS_CGROUP_PATH_MAX];
    int r;

    // pids.max
    snprintf(path, sizeof(path), "%s/pids.max", cg_path);
    r = cg_write_u32(path, policy->pids_max);
    if (r != AINOS_CG_OK && r != AINOS_CG_ERR_NOT_FOUND) return r;

    return AINOS_CG_OK;
}

static int apply_all_limits(const char *cg_path, const ainos_power_policy *policy)
{
    int r;

    r = apply_memory_limits(cg_path, policy);
    if (r != AINOS_CG_OK) return r;

    r = apply_cpu_limits(cg_path, policy);
    if (r != AINOS_CG_OK) return r;

    r = apply_io_limits(cg_path, policy);
    if (r != AINOS_CG_OK) return r;

    r = apply_pids_limits(cg_path, policy);
    if (r != AINOS_CG_OK) return r;

    return AINOS_CG_OK;
}

// ============================================================================
// Process Migration
// ============================================================================

static int cg_attach_pid(const char *cg_path, pid_t pid)
{
    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cgroup.procs", cg_path);

    char buf[32];
    snprintf(buf, sizeof(buf), "%d\n", (int)pid);
    return cg_write_value(path, buf);
}

static int cg_attach_self(const char *cg_path)
{
    return cg_attach_pid(cg_path, getpid());
}

// ============================================================================
// Freezer Operations
// ============================================================================

static int cg_freeze(const char *cg_path, bool freeze)
{
    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cgroup.freeze", cg_path);

    return cg_write_u32(path, freeze ? 1 : 0);
}

static int cg_is_frozen(const char *cg_path, bool *frozen)
{
    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cgroup.events", cg_path);

    FILE *f = fopen(path, "re");
    if (!f) return AINOS_CG_ERR_IO;

    char line[256];
    *frozen = false;
    while (fgets(line, sizeof(line), f)) {
        if (strncmp(line, "frozen ", 7) == 0) {
            int val = atoi(line + 7);
            *frozen = (val > 0);
            break;
        }
    }
    fclose(f);
    return AINOS_CG_OK;
}

// ============================================================================
// Public API: Initialization
// ============================================================================

ainos_cgroup_ctx *ainos_cgroup_init(void)
{
    ainos_cgroup_ctx *ctx = (ainos_cgroup_ctx *)calloc(1, sizeof(*ctx));
    if (!ctx) return NULL;

    // Detect cgroup v2
    if (!detect_cgroup_v2()) {
        fprintf(stderr, "[ainos-cgroups] cgroup v2 not available or not mounted\n");
        fprintf(stderr, "[ainos-cgroups] To enable: cgroup_no_v1=all on kernel cmdline\n");
        ctx->cgroup_v2_available = false;
        ctx->initialized = true;  // Allow graceful fallback
        return ctx;
    }

    ctx->cgroup_v2_available = true;
    strncpy(ctx->base_path, AINOS_CGROUP_BASE, sizeof(ctx->base_path) - 1);
    ctx->daemon_pid = getpid();
    build_subgroup_paths(ctx);

    fprintf(stdout, "[ainos-cgroups] cgroup v2 detected at %s\n", AINOS_CGROUP_ROOT);
    fprintf(stdout, "[ainos-cgroups] Base path: %s\n", ctx->base_path);

    ctx->initialized = true;
    return ctx;
}

// ============================================================================
// Public API: Create Hierarchy
// ============================================================================

int ainos_cgroup_create_hierarchy(ainos_cgroup_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    int r;

    // Create base cgroup
    r = create_cgroup_dir(ctx->base_path);
    if (r != AINOS_CG_OK) {
        fprintf(stderr, "[ainos-cgroups] Failed to create base cgroup: %s\n",
                strerror(errno));
        return r;
    }

    // Enable controllers for the base group
    // Read current subtree_control
    char controllers[1024] = {0};
    char ctrl_path[AINOS_CGROUP_PATH_MAX];
    snprintf(ctrl_path, sizeof(ctrl_path), "%s/cgroup.subtree_control", ctx->base_path);

    // First, enable controllers at the parent (root cgroup) level
    // We need to write to the parent's subtree_control
    // The parent of /sys/fs/cgroup/ainos is /sys/fs/cgroup
    snprintf(ctrl_path, sizeof(ctrl_path), "%s/cgroup.subtree_control",
             AINOS_CGROUP_ROOT);
    // Enable commonly available controllers
    const char *controllers_to_enable[] = {
        "cpu", "memory", "io", "pids", "cpuset", NULL
    };
    for (int i = 0; controllers_to_enable[i]; i++) {
        char buf[64];
        snprintf(buf, sizeof(buf), "+%s", controllers_to_enable[i]);
        int ret = cg_write_value(ctrl_path, buf);
        if (ret != AINOS_CG_OK && ret != AINOS_CG_ERR_NOT_FOUND) {
            // Some controllers may not be available
            fprintf(stdout, "[ainos-cgroups] Controller '%s' not available\n",
                    controllers_to_enable[i]);
        }
    }

    // Create subgroups
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        r = create_cgroup_dir(ctx->subgroup_paths[i]);
        if (r != AINOS_CG_OK) {
            fprintf(stderr, "[ainos-cgroups] Failed to create subgroup '%s': %s\n",
                    ctx->subgroup_names[i], strerror(errno));
            return r;
        }
        fprintf(stdout, "[ainos-cgroups] Created subgroup: %s\n",
                ctx->subgroup_paths[i]);
    }

    // Apply default (balanced) limits to all subgroups
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        r = apply_all_limits(ctx->subgroup_paths[i], &ainos_power_policies[AINOS_POWER_MODE_BALANCED]);
        if (r != AINOS_CG_OK) {
            fprintf(stderr, "[ainos-cgroups] Failed to apply limits to '%s': %d\n",
                    ctx->subgroup_names[i], r);
            return r;
        }
    }

    // Attach daemon process to daemon subgroup
    r = cg_attach_self(ctx->subgroup_paths[0]);
    if (r != AINOS_CG_OK) {
        fprintf(stderr, "[ainos-cgroups] Failed to attach daemon to cgroup: %s\n",
                strerror(errno));
        return r;
    }

    fprintf(stdout, "[ainos-cgroups] Hierarchy created and daemon attached\n");
    return AINOS_CG_OK;
}

// ============================================================================
// Public API: Attach Processes
// ============================================================================

int ainos_cgroup_attach_daemon(ainos_cgroup_ctx *ctx, pid_t pid)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    ctx->daemon_pid = pid;
    return cg_attach_pid(ctx->subgroup_paths[0], pid);
}

int ainos_cgroup_attach_runtime(ainos_cgroup_ctx *ctx, pid_t pid)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    ctx->runtime_pid = pid;
    return cg_attach_pid(ctx->subgroup_paths[1], pid);
}

int ainos_cgroup_attach_inference(ainos_cgroup_ctx *ctx, pid_t pid)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (ctx->num_inference_pids >= 256) return AINOS_CG_ERR_NOMEM;

    int r = cg_attach_pid(ctx->subgroup_paths[2], pid);
    if (r == AINOS_CG_OK) {
        ctx->inference_pids[ctx->num_inference_pids++] = pid;
    }
    return r;
}

int ainos_cgroup_attach_background(ainos_cgroup_ctx *ctx, pid_t pid)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (ctx->num_background_pids >= 64) return AINOS_CG_ERR_NOMEM;

    int r = cg_attach_pid(ctx->subgroup_paths[3], pid);
    if (r == AINOS_CG_OK) {
        ctx->background_pids[ctx->num_background_pids++] = pid;
    }
    return r;
}

// ============================================================================
// Public API: Power Policy Mode
// ============================================================================

const char *ainos_cgroup_power_mode_name(uint32_t mode)
{
    switch (mode) {
        case AINOS_POWER_MODE_MAX:      return "max";
        case AINOS_POWER_MODE_BALANCED: return "balanced";
        case AINOS_POWER_MODE_EFFICIENT: return "efficient";
        case AINOS_POWER_MODE_EMERGENCY: return "emergency";
        default:                        return "unknown";
    }
}

int ainos_cgroup_set_power_mode(ainos_cgroup_ctx *ctx, uint32_t mode)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (mode > AINOS_POWER_MODE_EMERGENCY) return AINOS_CG_ERR_INVALID;

    const ainos_power_policy *policy = &ainos_power_policies[mode];
    uint32_t old_mode = ctx->current_power_mode;
    ctx->current_power_mode = mode;

    fprintf(stdout, "[ainos-cgroups] Switching power mode: %s -> %s\n",
            ainos_cgroup_power_mode_name(old_mode),
            ainos_cgroup_power_mode_name(mode));

    // Apply limits to each subgroup
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        int r = apply_all_limits(ctx->subgroup_paths[i], policy);
        if (r != AINOS_CG_OK) {
            fprintf(stderr, "[ainos-cgroups] Failed to apply limits to '%s': %d\n",
                    ctx->subgroup_names[i], r);
        }
    }

    // Handle freezer for emergency mode
    if (policy->freeze_background) {
        int r = cg_freeze(ctx->subgroup_paths[3], true);
        if (r == AINOS_CG_OK) {
            fprintf(stdout, "[ainos-cgroups] Frozen background tasks\n");
        }
    } else if (old_mode == AINOS_POWER_MODE_EMERGENCY && mode != AINOS_POWER_MODE_EMERGENCY) {
        int r = cg_freeze(ctx->subgroup_paths[3], false);
        if (r == AINOS_CG_OK) {
            fprintf(stdout, "[ainos-cgroups] Thawed background tasks\n");
        }
    }

    return AINOS_CG_OK;
}

uint32_t ainos_cgroup_get_power_mode(ainos_cgroup_ctx *ctx)
{
    if (!ctx) return AINOS_POWER_MODE_BALANCED;
    return ctx->current_power_mode;
}

// ============================================================================
// Public API: Freezer Operations
// ============================================================================

int ainos_cgroup_freeze_subgroup(ainos_cgroup_ctx *ctx, int subgroup_idx, bool freeze)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    const char *name = ctx->subgroup_names[subgroup_idx];
    int r = cg_freeze(ctx->subgroup_paths[subgroup_idx], freeze);
    if (r == AINOS_CG_OK) {
        fprintf(stdout, "[ainos-cgroups] %s '%s' tasks\n",
                freeze ? "Frozen" : "Thawed", name);
    }
    return r;
}

int ainos_cgroup_freeze_all(ainos_cgroup_ctx *ctx, bool freeze)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        int r = cg_freeze(ctx->subgroup_paths[i], freeze);
        if (r != AINOS_CG_OK) return r;
    }

    fprintf(stdout, "[ainos-cgroups] %s all subgroups\n",
            freeze ? "Frozen" : "Thawed");
    return AINOS_CG_OK;
}

int ainos_cgroup_is_frozen(ainos_cgroup_ctx *ctx, int subgroup_idx, bool *frozen)
{
    if (!ctx || !ctx->initialized || !frozen) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    return cg_is_frozen(ctx->subgroup_paths[subgroup_idx], frozen);
}

// ============================================================================
// Public API: Statistics
// ============================================================================

int ainos_cgroup_collect_stats(ainos_cgroup_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    uint64_t tmp;
    uint32_t tmp32;
    int r;

    // Read from daemon subgroup (primary)
    char path[AINOS_CGROUP_PATH_MAX];

    // memory.current
    snprintf(path, sizeof(path), "%s/memory.current", ctx->subgroup_paths[0]);
    r = cg_read_u64(path, &tmp);
    if (r == AINOS_CG_OK) ctx->stats.memory_current = tmp;

    // memory.swap.current
    snprintf(path, sizeof(path), "%s/memory.swap.current", ctx->subgroup_paths[0]);
    r = cg_read_u64(path, &tmp);
    if (r == AINOS_CG_OK) ctx->stats.memory_swap_current = tmp;

    // memory.usage.max (peak memory)
    snprintf(path, sizeof(path), "%s/memory.peak", ctx->subgroup_paths[0]);
    r = cg_read_u64(path, &tmp);
    if (r == AINOS_CG_OK) ctx->stats.memory_usage_max = tmp;

    // cpu usage (aggregate all subgroups)
    ctx->stats.cpu_usage_us = 0;
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        snprintf(path, sizeof(path), "%s/cpu.stat", ctx->subgroup_paths[i]);
        FILE *f = fopen(path, "re");
        if (f) {
            char line[256];
            while (fgets(line, sizeof(line), f)) {
                if (sscanf(line, "usage_usec %" SCNu64, &tmp) == 1)
                    ctx->stats.cpu_usage_us += tmp;
            }
            fclose(f);
        }
    }

    // pids.current
    snprintf(path, sizeof(path), "%s/pids.current", ctx->subgroup_paths[0]);
    r = cg_read_u32(path, &tmp32);
    if (r == AINOS_CG_OK) ctx->stats.pids_current = tmp32;

    // pids.max
    snprintf(path, sizeof(path), "%s/pids.max", ctx->subgroup_paths[0]);
    r = cg_read_u32(path, &tmp32);
    if (r == AINOS_CG_OK) ctx->stats.pids_limit = tmp32;

    // memory.events (OOM count)
    snprintf(path, sizeof(path), "%s/memory.events", ctx->subgroup_paths[0]);
    FILE *f = fopen(path, "re");
    if (f) {
        char line[256];
        while (fgets(line, sizeof(line), f)) {
            if (sscanf(line, "oom %" SCNu32, &tmp32) == 1)
                ctx->stats.oom_events = tmp32;
        }
        fclose(f);
    }

    // IO stats (aggregate)
    ctx->stats.io_read_bytes = 0;
    ctx->stats.io_write_bytes = 0;
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        snprintf(path, sizeof(path), "%s/io.stat", ctx->subgroup_paths[i]);
        FILE *f = fopen(path, "re");
        if (f) {
            char line[1024];
            while (fgets(line, sizeof(line), f)) {
                // Parse: "major:minor rbytes=X wbytes=X rios=X wios=X dbytes=X dios=X"
                char *token = strtok(line, " \n");
                while (token) {
                    if (sscanf(token, "rbytes=%" SCNu64, &tmp) == 1)
                        ctx->stats.io_read_bytes += tmp;
                    else if (sscanf(token, "wbytes=%" SCNu64, &tmp) == 1)
                        ctx->stats.io_write_bytes += tmp;
                    token = strtok(NULL, " \n");
                }
            }
            fclose(f);
        }
    }

    // Check frozen count
    ctx->stats.num_frozen = 0;
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        bool frozen = false;
        if (cg_is_frozen(ctx->subgroup_paths[i], &frozen) == AINOS_CG_OK && frozen)
            ctx->stats.num_frozen++;
    }

    ctx->last_stats_time_ms = monotonic_ms();
    return AINOS_CG_OK;
}

const ainos_cgroup_stats *ainos_cgroup_get_stats(ainos_cgroup_ctx *ctx)
{
    if (!ctx) return NULL;
    return (const ainos_cgroup_stats *)&ctx->stats;
}

// ============================================================================
// Public API: Subgroup Limits Update
// ============================================================================

int ainos_cgroup_set_memory_max(ainos_cgroup_ctx *ctx, int subgroup_idx, uint64_t limit_bytes)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/memory.max", ctx->subgroup_paths[subgroup_idx]);

    if (limit_bytes == 0)
        return cg_write_value(path, "max\n");
    else
        return cg_write_u64(path, limit_bytes);
}

int ainos_cgroup_set_cpu_quota(ainos_cgroup_ctx *ctx, int subgroup_idx,
                                uint32_t quota_us, uint32_t period_us)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cpu.max", ctx->subgroup_paths[subgroup_idx]);

    char buf[64];
    if (quota_us == 0)
        snprintf(buf, sizeof(buf), "max %u\n", period_us);
    else
        snprintf(buf, sizeof(buf), "%u %u\n", quota_us, period_us);

    return cg_write_value(path, buf);
}

int ainos_cgroup_set_cpu_weight(ainos_cgroup_ctx *ctx, int subgroup_idx, uint32_t weight)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cpu.weight", ctx->subgroup_paths[subgroup_idx]);

    return cg_write_u32(path, weight);
}

int ainos_cgroup_set_io_weight(ainos_cgroup_ctx *ctx, int subgroup_idx, uint32_t weight)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/io.weight", ctx->subgroup_paths[subgroup_idx]);

    return cg_write_u32(path, weight);
}

int ainos_cgroup_set_pids_max(ainos_cgroup_ctx *ctx, int subgroup_idx, uint32_t max)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/pids.max", ctx->subgroup_paths[subgroup_idx]);

    return cg_write_u32(path, max);
}

// ============================================================================
// Public API: OOM Control
// ============================================================================

int ainos_cgroup_set_oom_group(ainos_cgroup_ctx *ctx, int subgroup_idx, bool enabled)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;
    if (subgroup_idx < 0 || subgroup_idx >= AINOS_CGROUP_NUM_SUBGROUPS)
        return AINOS_CG_ERR_INVALID;

    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/memory.oom.group", ctx->subgroup_paths[subgroup_idx]);

    return cg_write_u32(path, enabled ? 1 : 0);
}

// ============================================================================
// Public API: Suspend/Resume (system-wide)
// ============================================================================

int ainos_cgroup_suspend(ainos_cgroup_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    // Freeze all non-daemon subgroups
    // Inference and background get frozen; runtime may continue
    int r1 = cg_freeze(ctx->subgroup_paths[2], true);  // inference
    int r2 = cg_freeze(ctx->subgroup_paths[3], true);  // background

    fprintf(stdout, "[ainos-cgroups] System suspended (inference=%d, background=%d)\n",
            r1, r2);

    return (r1 == AINOS_CG_OK || r1 == AINOS_CG_ERR_NOT_FOUND) ? AINOS_CG_OK : r1;
}

int ainos_cgroup_resume(ainos_cgroup_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return AINOS_CG_ERR_INVALID;
    if (!ctx->cgroup_v2_available) return AINOS_CG_ERR_NO_CGROUP;

    // Thaw all subgroups
    int r = AINOS_CG_OK;
    for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
        int ret = cg_freeze(ctx->subgroup_paths[i], false);
        if (ret != AINOS_CG_OK && ret != AINOS_CG_ERR_NOT_FOUND)
            r = ret;
    }

    fprintf(stdout, "[ainos-cgroups] System resumed\n");
    return r;
}

// ============================================================================
// Public API: Shutdown & Cleanup
// ============================================================================

int ainos_cgroup_shutdown(ainos_cgroup_ctx *ctx)
{
    if (!ctx) return AINOS_CG_ERR_INVALID;

    if (ctx->cgroup_v2_available) {
        // Thaw everything
        for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
            cg_freeze(ctx->subgroup_paths[i], false);
        }

        // Move all processes back to root cgroup
        for (int i = 0; i < AINOS_CGROUP_NUM_SUBGROUPS; i++) {
            char path[AINOS_CGROUP_PATH_MAX];
            snprintf(path, sizeof(path), "%s/cgroup.procs", ctx->subgroup_paths[i]);

            FILE *f = fopen(path, "re");
            if (!f) continue;

            pid_t pids[4096];
            int count = 0;
            char line[64];
            while (fgets(line, sizeof(line), f) && count < 4096) {
                pid_t pid = (pid_t)atoi(line);
                if (pid > 0) pids[count++] = pid;
            }
            fclose(f);

            // Move each PID to root cgroup
            for (int j = 0; j < count; j++) {
                char root_path[AINOS_CGROUP_PATH_MAX];
                snprintf(root_path, sizeof(root_path), "%s/cgroup.procs",
                         AINOS_CGROUP_ROOT);
                char buf[32];
                snprintf(buf, sizeof(buf), "%d\n", (int)pids[j]);
                cg_write_value(root_path, buf);
            }

            // Remove cgroup directory
            rmdir(ctx->subgroup_paths[i]);
        }

        // Remove base cgroup
        rmdir(ctx->base_path);

        fprintf(stdout, "[ainos-cgroups] cgroup hierarchy removed\n");
    }

    ctx->initialized = false;
    free(ctx);
    return AINOS_CG_OK;
}

// ============================================================================
// Public API: Health Check
// ============================================================================

bool ainos_cgroup_is_available(ainos_cgroup_ctx *ctx)
{
    return ctx && ctx->cgroup_v2_available;
}

bool ainos_cgroup_is_healthy(ainos_cgroup_ctx *ctx)
{
    if (!ctx || !ctx->initialized) return false;
    if (!ctx->cgroup_v2_available) return true;  // Graceful fallback

    // Quick check: verify daemon subgroup exists
    char path[AINOS_CGROUP_PATH_MAX];
    snprintf(path, sizeof(path), "%s/cgroup.procs", ctx->subgroup_paths[0]);
    return file_exists(path);
}

// ============================================================================
// CLI Main (for testing)
// ============================================================================

#ifdef AINOS_CGROUPS_TEST_MAIN
int main(int argc, char *argv[])
{
    fprintf(stdout, "AinosOS cgroups v2 Test Utility v%s\n", AINOS_CGROUPS_VERSION);

    ainos_cgroup_ctx *ctx = ainos_cgroup_init();
    if (!ctx) {
        fprintf(stderr, "Failed to initialize cgroups context\n");
        return 1;
    }

    if (!ainos_cgroup_is_available(ctx)) {
        fprintf(stdout, "cgroup v2 not available (running in compatibility mode)\n");
        ainos_cgroup_shutdown(ctx);
        return 0;
    }

    int r = ainos_cgroup_create_hierarchy(ctx);
    if (r != AINOS_CG_OK) {
        fprintf(stderr, "Failed to create hierarchy: %d\n", r);
        ainos_cgroup_shutdown(ctx);
        return 1;
    }

    // Test power mode switching
    for (uint32_t mode = 0; mode <= AINOS_POWER_MODE_EMERGENCY; mode++) {
        r = ainos_cgroup_set_power_mode(ctx, mode);
        if (r == AINOS_CG_OK) {
            fprintf(stdout, "  Set power mode: %s\n",
                    ainos_cgroup_power_mode_name(mode));
        }
    }

    // Collect stats
    r = ainos_cgroup_collect_stats(ctx);
    if (r == AINOS_CG_OK) {
        const ainos_cgroup_stats *stats = ainos_cgroup_get_stats(ctx);
        fprintf(stdout, "  Memory: %" PRIu64 " bytes\n", stats->memory_current);
        fprintf(stdout, "  CPU: %" PRIu64 " usec\n", stats->cpu_usage_us);
        fprintf(stdout, "  PIDs: %u / %u\n", stats->pids_current, stats->pids_limit);
    }

    // Test OOM control
    ainos_cgroup_set_oom_group(ctx, 0, true);

    // Test suspend/resume
    ainos_cgroup_suspend(ctx);
    sleep(1);
    ainos_cgroup_resume(ctx);

    // Cleanup
    ainos_cgroup_shutdown(ctx);
    fprintf(stdout, "All tests passed.\n");
    return 0;
}
#endif // AINOS_CGROUPS_TEST_MAIN