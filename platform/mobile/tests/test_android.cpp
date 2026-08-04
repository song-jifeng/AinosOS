/**
 * test_android.cpp
 * Android platform tests for Ainos mobile support layer
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos/platform_mobile.h"
#include "ainos_mobile_common.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

static int tests_passed = 0;
static int tests_failed = 0;
static int test_count = 0;

#define TEST(name) \
    do { \
        test_count++; \
        printf("  TEST %d: %s ... ", test_count, name); \
    } while(0)

#define PASS() \
    do { \
        tests_passed++; \
        printf("PASSED\n"); \
    } while(0)

#define FAIL(msg) \
    do { \
        tests_failed++; \
        printf("FAILED: %s\n", msg); \
    } while(0)

#define ASSERT(cond, msg) \
    do { \
        if (!(cond)) { \
            FAIL(msg); \
            return; \
        } \
    } while(0)

/*============================================================================
 * Test: Platform Initialization
 *============================================================================*/

static void test_platform_init(void)
{
    TEST("Platform initialization");

    ainos_status_t status = ainos_platform_init("TestApp", "1.0.0", NULL);
    ASSERT(status == AINOS_OK, "Init should return OK");

    // Should fail on re-initialization
    status = ainos_platform_init("TestApp", "1.0.0", NULL);
    ASSERT(status == AINOS_ERROR_ALREADY_INITIALIZED, "Re-init should fail");

    // Check initialized
    ASSERT(ainos_platform_is_initialized() == true, "Should be initialized");

    // Check version
    const char* version = ainos_platform_version();
    ASSERT(version != NULL, "Version should not be NULL");
    ASSERT(strlen(version) > 0, "Version should not be empty");

    // Check platform detection
    ainos_platform_type_t type = ainos_platform_detect();
    ASSERT(type == AINOS_PLATFORM_ANDROID, "Should detect Android");

    // Shutdown
    ainos_platform_shutdown();
    ASSERT(ainos_platform_is_initialized() == false, "Should not be initialized after shutdown");

    PASS();
}

static void test_platform_init_invalid_params(void)
{
    TEST("Platform init with invalid params");

    ainos_status_t status = ainos_platform_init(NULL, "1.0.0", NULL);
    ASSERT(status == AINOS_ERROR_INVALID_PARAM, "NULL app_name should fail");

    status = ainos_platform_init("TestApp", NULL, NULL);
    ASSERT(status == AINOS_ERROR_INVALID_PARAM, "NULL app_version should fail");

    PASS();
}

/*============================================================================
 * Test: Thermal Management
 *============================================================================*/

static void test_thermal_management(void)
{
    TEST("Thermal management");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Get thermal status
    ainos_thermal_status_t status = ainos_thermal_get_status();
    ASSERT(status >= AINOS_THERMAL_STATUS_NORMAL &&
           status <= AINOS_THERMAL_STATUS_UNKNOWN,
           "Thermal status should be valid");

    // Get throttle level
    ainos_thermal_throttle_t throttle = ainos_thermal_get_throttle_level();
    ASSERT(throttle >= AINOS_THERMAL_THROTTLE_NONE &&
           throttle <= AINOS_THERMAL_THROTTLE_SHUTDOWN,
           "Throttle level should be valid");

    // Get CPU temperature
    float cpu_temp = 0.0f;
    ainos_status_t result = ainos_thermal_get_cpu_temperature(&cpu_temp);
    ASSERT(result == AINOS_OK, "CPU temperature should succeed");
    ASSERT(cpu_temp > 0.0f, "CPU temperature should be positive");

    // Get battery temperature
    float batt_temp = 0.0f;
    result = ainos_thermal_get_battery_temperature(&batt_temp);
    ASSERT(result == AINOS_OK, "Battery temperature should succeed");
    ASSERT(batt_temp > 0.0f, "Battery temperature should be positive");

    // Get recommended batch size
    int batch_size = ainos_thermal_get_recommended_batch_size();
    ASSERT(batch_size >= 1 && batch_size <= 32, "Batch size should be 1-32");

    // Check throttle inference
    bool should_throttle = ainos_thermal_should_throttle_inference();
    ASSERT(should_throttle == false || should_throttle == true,
           "Should throttle should be boolean");

    // Register and unregister callback
    result = ainos_thermal_register_callback(NULL, NULL);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "NULL callback should fail");

    bool callback_called = false;
    result = ainos_thermal_register_callback(
        [](ainos_thermal_status_t old_s, ainos_thermal_status_t new_s, void* user_data) {
            bool* called = (bool*)user_data;
            *called = true;
        }, &callback_called);
    ASSERT(result == AINOS_OK, "Register callback should succeed");

    // Simulate a status change
    if (g_ainos_state.thermal_callback) {
        g_ainos_state.thermal_callback(AINOS_THERMAL_STATUS_NORMAL,
                                        AINOS_THERMAL_STATUS_WARM,
                                        g_ainos_state.thermal_callback_userdata);
    }

    ainos_thermal_unregister_callback();
    ASSERT(g_ainos_state.thermal_callback == NULL, "Callback should be NULL after unregister");

    // Status to string
    const char* str = ainos_thermal_status_to_string(AINOS_THERMAL_STATUS_NORMAL);
    ASSERT(str != NULL, "Status string should not be NULL");
    ASSERT(strcmp(str, "Normal") == 0, "Status string should be Normal");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Battery Management
 *============================================================================*/

static void test_battery_management(void)
{
    TEST("Battery management");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Get battery level
    int level = -1;
    ainos_status_t result = ainos_battery_get_level(&level);
    ASSERT(result == AINOS_OK, "Get level should succeed");
    ASSERT(level >= 0 && level <= 100, "Level should be 0-100");

    // Get battery status
    ainos_battery_status_t status = ainos_battery_get_status();
    ASSERT(status >= AINOS_BATTERY_STATUS_UNKNOWN &&
           status <= AINOS_BATTERY_STATUS_NOT_CHARGING,
           "Status should be valid");

    // Get power mode
    ainos_power_mode_t mode = ainos_battery_get_power_mode();
    ASSERT(mode >= AINOS_POWER_MODE_NORMAL &&
           mode <= AINOS_POWER_MODE_PERFORMANCE,
           "Power mode should be valid");

    // Check low power mode
    bool low_power = ainos_battery_is_low_power_mode();
    ASSERT(low_power == true || low_power == false, "Low power should be boolean");

    // Check charging
    bool charging = ainos_battery_is_charging();
    ASSERT(charging == true || charging == false, "Charging should be boolean");

    // Get estimated time
    int minutes = 0;
    result = ainos_battery_get_estimated_time(&minutes);
    ASSERT(result == AINOS_OK, "Get estimated time should succeed");
    ASSERT(minutes >= 0, "Minutes should be >= 0");

    // Request power mode
    result = ainos_battery_request_power_mode(AINOS_POWER_MODE_LOW_POWER);
    ASSERT(result == AINOS_OK, "Request power mode should succeed");
    ASSERT(ainos_battery_get_power_mode() == AINOS_POWER_MODE_LOW_POWER,
           "Power mode should be updated");

    // Reset to normal
    ainos_battery_request_power_mode(AINOS_POWER_MODE_NORMAL);

    // Register/unregister callback
    result = ainos_battery_register_callback(NULL, NULL);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "NULL callback should fail");

    result = ainos_battery_register_callback(
        [](ainos_battery_status_t s, int l, void* u) {}, NULL);
    ASSERT(result == AINOS_OK, "Register callback should succeed");

    ainos_battery_unregister_callback();
    ASSERT(g_ainos_state.battery_callback == NULL, "Callback should be NULL after unregister");

    // Status to string
    const char* str = ainos_battery_status_to_string(AINOS_BATTERY_STATUS_CHARGING);
    ASSERT(str != NULL, "Status string should not be NULL");
    ASSERT(strcmp(str, "Charging") == 0, "Status string should be Charging");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Permission Management
 *============================================================================*/

static void test_permissions(void)
{
    TEST("Permission management");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Check permission
    ainos_permission_state_t state;
    ainos_status_t result = ainos_permission_check(AINOS_PERMISSION_CAMERA, &state);
    ASSERT(result == AINOS_OK, "Check permission should succeed");

    // Request permission
    bool callback_called = false;
    result = ainos_permission_request(AINOS_PERMISSION_MICROPHONE,
        [](ainos_permission_t p, ainos_permission_state_t s, void* u) {
            bool* called = (bool*)u;
            *called = true;
        }, &callback_called);
    ASSERT(result == AINOS_OK, "Request permission should succeed");
    ASSERT(callback_called == true, "Callback should be called");

    // Request multiple permissions
    ainos_permission_t perms[] = {
        AINOS_PERMISSION_STORAGE,
        AINOS_PERMISSION_NOTIFICATIONS,
        AINOS_PERMISSION_BLUETOOTH
    };
    int multi_callback_count = 0;
    result = ainos_permission_request_multiple(perms, 3,
        [](ainos_permission_t p, ainos_permission_state_t s, void* u) {
            int* count = (int*)u;
            (*count)++;
        }, &multi_callback_count);
    ASSERT(result == AINOS_OK, "Request multiple should succeed");
    ASSERT(multi_callback_count == 3, "Callback should be called 3 times");

    // Open settings
    result = ainos_permission_open_settings();
    ASSERT(result == AINOS_OK, "Open settings should succeed");

    // Should show rationale
    bool rationale = ainos_permission_should_show_rationale(AINOS_PERMISSION_CAMERA);
    ASSERT(rationale == true || rationale == false, "Rationale should be boolean");

    // Get name
    const char* name = ainos_permission_get_name(AINOS_PERMISSION_CAMERA);
    ASSERT(name != NULL, "Name should not be NULL");
    ASSERT(strcmp(name, "Camera") == 0, "Name should be Camera");

    // Invalid permission
    result = ainos_permission_check((ainos_permission_t)999, &state);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "Invalid permission should fail");

    name = ainos_permission_get_name((ainos_permission_t)999);
    ASSERT(name != NULL, "Name for invalid should not be NULL");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Model Management
 *============================================================================*/

static void test_model_management(void)
{
    TEST("Model management");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Init model system
    ainos_status_t result = ainos_model_init("/tmp/ainos_test_models", 1024);
    ASSERT(result == AINOS_OK, "Model init should succeed");

    // Get available models
    ainos_model_info_t* models = NULL;
    size_t count = 0;
    result = ainos_model_get_available(&models, &count);
    ASSERT(result == AINOS_OK, "Get available models should succeed");
    ASSERT(count > 0, "Should have at least one model");
    ASSERT(models != NULL, "Models should not be NULL");

    // Get model info
    ainos_model_info_t info;
    result = ainos_model_get_info("ainos-llm-7b-q4", &info);
    ASSERT(result == AINOS_OK, "Get model info should succeed");
    ASSERT(strcmp(info.model_id, "ainos-llm-7b-q4") == 0, "Model ID should match");
    ASSERT(info.parameter_count == 7000000000, "Parameter count should match");

    // Get info for non-existent model
    result = ainos_model_get_info("non-existent-model", &info);
    ASSERT(result == AINOS_ERROR_MODEL_NOT_FOUND, "Non-existent model should fail");

    // Download model
    result = ainos_model_download("ainos-llm-7b-q4", NULL, NULL);
    ASSERT(result == AINOS_OK, "Download should succeed");

    // Cancel download
    result = ainos_model_cancel_download("ainos-llm-7b-q4");
    ASSERT(result == AINOS_OK, "Cancel download should succeed");

    // Load model
    result = ainos_model_load("ainos-llm-1b-int8", NULL, NULL);
    ASSERT(result == AINOS_OK, "Load bundled model should succeed");

    // Check if loaded
    bool loaded = false;
    result = ainos_model_is_loaded("ainos-llm-1b-int8", &loaded);
    ASSERT(result == AINOS_OK, "Is loaded should succeed");
    ASSERT(loaded == true, "Model should be loaded");

    // Unload model
    result = ainos_model_unload("ainos-llm-1b-int8");
    ASSERT(result == AINOS_OK, "Unload should succeed");

    // Delete model
    result = ainos_model_delete("ainos-llm-1b-int8");
    ASSERT(result == AINOS_OK, "Delete should succeed");

    // Get cache size
    float used_mb = 0, total_mb = 0;
    result = ainos_model_get_cache_size(&used_mb, &total_mb);
    ASSERT(result == AINOS_OK, "Get cache size should succeed");
    ASSERT(total_mb == 1024.0f, "Total should be 1024 MB");

    // Clear cache
    result = ainos_model_clear_cache();
    ASSERT(result == AINOS_OK, "Clear cache should succeed");

    // Free list
    ainos_model_free_list(models, count);

    // Init with NULL cache dir
    result = ainos_model_init(NULL, 1024);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "NULL cache dir should fail");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Inference Engine
 *============================================================================*/

static void test_inference_engine(void)
{
    TEST("Inference engine");

    ainos_platform_init("TestApp", "1.0.0", NULL);
    ainos_model_init("/tmp/ainos_test_models", 1024);

    // Get default config
    ainos_inference_config_t config;
    ainos_inference_get_default_config(&config);
    ASSERT(config.backend == AINOS_INFERENCE_BACKEND_AUTO, "Default backend should be AUTO");
    ASSERT(config.num_threads == 4, "Default threads should be 4");
    ASSERT(config.use_gpu == true, "Default GPU should be enabled");
    ASSERT(config.allow_fp16 == true, "Default FP16 should be enabled");
    ASSERT(config.timeout_ms == 30000, "Default timeout should be 30000");

    // Init inference
    ainos_status_t result = ainos_inference_init(&config);
    ASSERT(result == AINOS_OK, "Inference init should succeed");

    // Load a model
    ainos_model_load("ainos-llm-1b-int8", NULL, NULL);

    // Run inference
    ainos_tensor_t input;
    memset(&input, 0, sizeof(input));
    input.size = 128;
    input.data = (int32_t*)calloc(input.size, sizeof(int32_t));
    input.num_dimensions = 1;
    input.dimensions[0] = input.size;

    ainos_tensor_t* output = NULL;
    result = ainos_inference_run("ainos-llm-1b-int8", &input, &output);
    ASSERT(result == AINOS_OK, "Inference run should succeed");
    ASSERT(output != NULL, "Output should not be NULL");

    ainos_inference_free_tensor(output);
    free(input.data);

    // Run async inference
    bool async_callback_called = false;
    result = ainos_inference_run_async("ainos-llm-1b-int8", &input,
        [](ainos_status_t s, const ainos_inference_result_t* r, void* u) {
            bool* called = (bool*)u;
            *called = true;
        }, &async_callback_called);
    ASSERT(result == AINOS_OK, "Async inference should succeed");

    // Run streaming inference
    bool stream_started = false;
    bool stream_completed = false;
    result = ainos_inference_run_stream("ainos-llm-1b-int8", &input,
        [](const ainos_stream_event_data_t* e, void* u) {
            bool* started = (bool*)u;
            if (e->event == AINOS_STREAM_EVENT_START) *started = true;
        },
        [](ainos_status_t s, const ainos_inference_result_t* r, void* u) {
            bool* completed = (bool*)u;
            *completed = true;
        }, &stream_started);
    ASSERT(result == AINOS_OK, "Stream inference should succeed");

    // Get available backends
    ainos_inference_backend_t* backends = NULL;
    size_t backend_count = 0;
    result = ainos_inference_get_available_backends(&backends, &backend_count);
    ASSERT(result == AINOS_OK, "Get available backends should succeed");
    ASSERT(backend_count > 0, "Should have at least one backend");
    free(backends);

    // Get active backend
    ainos_inference_backend_t active = ainos_inference_get_active_backend();
    ASSERT(active >= AINOS_INFERENCE_BACKEND_AUTO &&
           active <= AINOS_INFERENCE_BACKEND_DELEGATE,
           "Active backend should be valid");

    // Cancel inference
    result = ainos_inference_cancel("ainos-llm-1b-int8");
    ASSERT(result == AINOS_OK, "Cancel inference should succeed");

    // Check if running
    bool running = false;
    result = ainos_inference_is_running("ainos-llm-1b-int8", &running);
    ASSERT(result == AINOS_OK, "Is running check should succeed");

    // Shutdown
    ainos_inference_shutdown();
    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Daemon Communication
 *============================================================================*/

static void test_daemon_communication(void)
{
    TEST("Daemon communication");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Connect to daemon
    ainos_status_t result = ainos_daemon_connect("127.0.0.1", 8732, 5000);
    ASSERT(result == AINOS_OK, "Connect should succeed");
    ASSERT(ainos_daemon_is_connected() == true, "Should be connected");

    // Reconnect should fail
    result = ainos_daemon_connect("127.0.0.1", 8732, 5000);
    ASSERT(result == AINOS_ERROR_ALREADY_INITIALIZED, "Reconnect should fail");

    // Get daemon status
    ainos_daemon_status_t status;
    result = ainos_daemon_get_status(&status);
    ASSERT(result == AINOS_OK, "Get status should succeed");
    ASSERT(status.connected == true, "Status should show connected");

    // Send heartbeat
    result = ainos_daemon_send_heartbeat();
    ASSERT(result == AINOS_OK, "Heartbeat should succeed");

    // Send command
    char response[256];
    size_t response_size = sizeof(response);
    result = ainos_daemon_send_command(
        AINOS_DAEMON_CMD_GET_STATUS, NULL, 0,
        response, &response_size, 5000);
    ASSERT(result == AINOS_OK, "Send command should succeed");

    // Register connection callback
    bool callback_called = false;
    result = ainos_daemon_register_connection_callback(
        [](bool connected, void* u) {
            bool* called = (bool*)u;
            *called = true;
        }, &callback_called);
    ASSERT(result == AINOS_OK, "Register callback should succeed");

    // Disconnect
    ainos_daemon_disconnect();
    ASSERT(ainos_daemon_is_connected() == false, "Should not be connected after disconnect");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Background Services
 *============================================================================*/

static void test_background_services(void)
{
    TEST("Background services");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Register background task
    ainos_background_task_config_t config;
    memset(&config, 0, sizeof(config));
    strncpy(config.task_id, "test_task", sizeof(config.task_id) - 1);
    strncpy(config.task_name, "Test Task", sizeof(config.task_name) - 1);
    config.type = AINOS_BACKGROUND_TASK_MAINTENANCE;
    config.interval_minutes = 60;
    config.max_execution_time_seconds = 300;
    config.requires_network = true;
    config.max_retries = 3;

    bool callback_called = false;
    ainos_status_t result = ainos_background_register_task(&config,
        [](const char* tid, ainos_status_t s, void* u) {
            bool* called = (bool*)u;
            *called = true;
        }, &callback_called);
    ASSERT(result == AINOS_OK, "Register task should succeed");

    // Duplicate registration should fail
    result = ainos_background_register_task(&config, NULL, NULL);
    ASSERT(result == AINOS_ERROR_ALREADY_INITIALIZED, "Duplicate register should fail");

    // Start task
    result = ainos_background_start_task("test_task");
    ASSERT(result == AINOS_OK, "Start task should succeed");
    ASSERT(callback_called == true, "Callback should be called");

    // Check task status
    bool running = false;
    result = ainos_background_task_status("test_task", &running);
    ASSERT(result == AINOS_OK, "Task status should succeed");
    ASSERT(running == true, "Task should be running");

    // Stop task
    result = ainos_background_stop_task("test_task");
    ASSERT(result == AINOS_OK, "Stop task should succeed");

    // Unregister task
    result = ainos_background_unregister_task("test_task");
    ASSERT(result == AINOS_OK, "Unregister task should succeed");

    // Invalid task
    result = ainos_background_start_task("non_existent");
    ASSERT(result == AINOS_ERROR_GENERAL, "Non-existent task should fail");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Notifications
 *============================================================================*/

static void test_notifications(void)
{
    TEST("Notifications");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Show notification
    ainos_notification_t notif;
    memset(&notif, 0, sizeof(notif));
    strncpy(notif.notification_id, "test_notif", sizeof(notif.notification_id) - 1);
    strncpy(notif.channel_id, "test_channel", sizeof(notif.channel_id) - 1);
    strncpy(notif.title, "Test Title", sizeof(notif.title) - 1);
    strncpy(notif.body, "Test Body", sizeof(notif.body) - 1);
    notif.priority = AINOS_NOTIFICATION_PRIORITY_DEFAULT;
    notif.auto_cancel = true;
    notif.vibrate = true;

    ainos_status_t result = ainos_notification_show(&notif);
    ASSERT(result == AINOS_OK, "Show notification should succeed");

    // Create channel
    result = ainos_notification_create_channel("test_channel", "Test Channel", 3);
    ASSERT(result == AINOS_OK, "Create channel should succeed");

    // Cancel notification
    result = ainos_notification_cancel("test_notif");
    ASSERT(result == AINOS_OK, "Cancel notification should succeed");

    // Cancel all
    result = ainos_notification_cancel_all();
    ASSERT(result == AINOS_OK, "Cancel all should succeed");

    // Delete channel
    result = ainos_notification_delete_channel("test_channel");
    ASSERT(result == AINOS_OK, "Delete channel should succeed");

    // Schedule notification
    notif.scheduled_time_ms = 60000;
    result = ainos_notification_schedule(&notif);
    ASSERT(result == AINOS_OK, "Schedule notification should succeed");

    // Register action callback
    result = ainos_notification_register_action_callback(NULL, NULL);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "NULL callback should fail");

    result = ainos_notification_register_action_callback(
        [](const char* nid, const char* action, void* u) {}, NULL);
    ASSERT(result == AINOS_OK, "Register action callback should succeed");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Foreground Service
 *============================================================================*/

static void test_foreground_service(void)
{
    TEST("Foreground service");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    ainos_foreground_service_config_t config;
    memset(&config, 0, sizeof(config));
    strncpy(config.service_name, "TestService", sizeof(config.service_name) - 1);
    strncpy(config.notification_title, "Test", sizeof(config.notification_title) - 1);
    strncpy(config.notification_text, "Running", sizeof(config.notification_text) - 1);
    config.notification_id = 1001;
    config.show_foreground_notification = true;
    config.keep_alive = true;

    ainos_status_t result = ainos_foreground_service_start(&config);
    ASSERT(result == AINOS_OK, "Start foreground service should succeed");

    // Duplicate start should fail
    result = ainos_foreground_service_start(&config);
    ASSERT(result == AINOS_ERROR_ALREADY_INITIALIZED, "Duplicate start should fail");

    // Check running
    bool running = false;
    result = ainos_foreground_service_is_running(&running);
    ASSERT(result == AINOS_OK, "Is running check should succeed");
    ASSERT(running == true, "Service should be running");

    // Update notification
    result = ainos_foreground_service_update_notification("Updated", "Still running");
    ASSERT(result == AINOS_OK, "Update notification should succeed");

    // Stop
    result = ainos_foreground_service_stop();
    ASSERT(result == AINOS_OK, "Stop should succeed");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Device Information
 *============================================================================*/

static void test_device_info(void)
{
    TEST("Device information");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    ainos_device_info_t info;
    ainos_status_t result = ainos_device_get_info(&info);
    ASSERT(result == AINOS_OK, "Get device info should succeed");
    ASSERT(strlen(info.device_model) > 0, "Device model should not be empty");
    ASSERT(info.cpu_cores > 0, "CPU cores should be > 0");
    ASSERT(info.total_ram_mb > 0, "Total RAM should be > 0");

    // Check minimum requirements
    bool meets_minimum = false;
    result = ainos_device_check_minimum_requirements(&meets_minimum);
    ASSERT(result == AINOS_OK, "Check minimum requirements should succeed");

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Test: Utility Functions
 *============================================================================*/

static void test_utilities(void)
{
    TEST("Utility functions");

    ainos_platform_init("TestApp", "1.0.0", NULL);

    // Status to string
    const char* str = ainos_status_to_string(AINOS_OK);
    ASSERT(str != NULL, "Status string should not be NULL");
    ASSERT(strcmp(str, "OK") == 0, "Status string should be OK");

    str = ainos_status_to_string(AINOS_ERROR_GENERAL);
    ASSERT(str != NULL, "Error string should not be NULL");

    // Timestamp
    int64_t ts = ainos_get_timestamp_ms();
    ASSERT(ts > 0, "Timestamp should be > 0");

    // UUID
    char uuid[37];
    ainos_status_t result = ainos_generate_uuid(uuid, sizeof(uuid));
    ASSERT(result == AINOS_OK, "UUID generation should succeed");
    ASSERT(strlen(uuid) == 36, "UUID should be 36 characters");

    // UUID with small buffer
    result = ainos_generate_uuid(uuid, 10);
    ASSERT(result == AINOS_ERROR_INVALID_PARAM, "Small buffer should fail");

    // Mkdir
    result = ainos_mkdir_p("/tmp/ainos_test/a/b/c");
    ASSERT(result == AINOS_OK, "Mkdir should succeed");

    // File exists
    bool exists = ainos_file_exists("/tmp");
    ASSERT(exists == true, "/tmp should exist");

    exists = ainos_file_exists("/tmp/nonexistent_file_xyz");
    ASSERT(exists == false, "Non-existent file should not exist");

    // File size
    uint64_t size = 0;
    result = ainos_file_size("/tmp", &size);
    ASSERT(result == AINOS_OK, "File size should succeed");

    // Format bytes
    char formatted[32];
    const char* fmt = ainos_format_bytes(1024, formatted, sizeof(formatted));
    ASSERT(fmt != NULL, "Formatted bytes should not be NULL");

    // Base64 encode
    const uint8_t test_data[] = "Hello, Ainos!";
    char b64_output[128];
    size_t b64_size = sizeof(b64_output);
    result = ainos_base64_encode(test_data, sizeof(test_data), b64_output, &b64_size);
    ASSERT(result == AINOS_OK, "Base64 encode should succeed");
    ASSERT(b64_size > 0, "Encoded size should be > 0");

    // Base64 decode
    uint8_t decoded[128];
    size_t decoded_size = sizeof(decoded);
    result = ainos_base64_decode(b64_output, decoded, &decoded_size);
    ASSERT(result == AINOS_OK, "Base64 decode should succeed");
    ASSERT(decoded_size == sizeof(test_data), "Decoded size should match original");

    // Cache dir
    char cache_dir[512];
    result = ainos_get_cache_dir(cache_dir, sizeof(cache_dir));
    ASSERT(result == AINOS_OK, "Get cache dir should succeed");

    // Data dir
    char data_dir[512];
    result = ainos_get_data_dir(data_dir, sizeof(data_dir));
    ASSERT(result == AINOS_OK, "Get data dir should succeed");

    // Sleep
    ainos_sleep(10);

    ainos_platform_shutdown();
    PASS();
}

/*============================================================================
 * Main Test Runner
 *============================================================================*/

int main(void)
{
    printf("============================================\n");
    printf("Ainos Android Platform Tests\n");
    printf("============================================\n\n");

    test_platform_init();
    test_platform_init_invalid_params();
    test_thermal_management();
    test_battery_management();
    test_permissions();
    test_model_management();
    test_inference_engine();
    test_daemon_communication();
    test_background_services();
    test_notifications();
    test_foreground_service();
    test_device_info();
    test_utilities();

    printf("\n============================================\n");
    printf("Test Results: %d passed, %d failed, %d total\n",
           tests_passed, tests_failed, test_count);
    printf("============================================\n");

    return tests_failed > 0 ? 1 : 0;
}