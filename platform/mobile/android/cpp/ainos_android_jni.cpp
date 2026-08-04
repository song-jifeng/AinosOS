/**
 * ainos_android_jni.cpp
 * JNI bridge implementation for Ainos Android platform
 *
 * Copyright (c) Ainos 2026
 */

#include "ainos_mobile_common.h"
#include <jni.h>
#include <android/log.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>

#define LOG_TAG "AinosJNI"

/*============================================================================
 * JNI Method Implementations
 *============================================================================*/

extern "C" {

/*============================================================================
 * AinosNative JNI Methods
 *============================================================================*/

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeInit(
    JNIEnv* env,
    jclass clazz,
    jstring app_name,
    jstring app_version)
{
    (void)clazz;
    const char* name = env->GetStringUTFChars(app_name, NULL);
    const char* version = env->GetStringUTFChars(app_version, NULL);

    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                        "nativeInit: %s v%s", name, version);

    ainos_status_t status = ainos_platform_init(name, version, NULL);

    env->ReleaseStringUTFChars(app_name, name);
    env->ReleaseStringUTFChars(app_version, version);

    return (jint)status;
}

JNIEXPORT void JNICALL
Java_com_ainos_AinosNative_nativeShutdown(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "nativeShutdown");
    ainos_platform_shutdown();
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeGetApiLevel(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    int api_level = 0;

    // Try reading system property
    FILE* fp = popen("getprop ro.build.version.sdk", "r");
    if (fp) {
        char buf[8] = {0};
        if (fgets(buf, sizeof(buf), fp)) {
            api_level = atoi(buf);
        }
        pclose(fp);
    }

    if (api_level == 0) {
        // Fallback: parse build.prop
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

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeGetThermalStatus(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_thermal_get_status();
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeGetBatteryLevel(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    int level;
    ainos_battery_get_level(&level);
    return (jint)level;
}

JNIEXPORT jboolean JNICALL
Java_com_ainos_AinosNative_nativeIsCharging(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    return ainos_battery_is_charging() ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jstring JNICALL
Java_com_ainos_AinosNative_nativeGetDeviceInfo(
    JNIEnv* env,
    jclass clazz)
{
    (void)clazz;
    ainos_device_info_t info;
    ainos_device_get_info(&info);

    char json[2048];
    snprintf(json, sizeof(json),
             "{\"model\":\"%s\",\"manufacturer\":\"%s\","
             "\"os_version\":\"%s\",\"cpu_cores\":%u,"
             "\"total_ram_mb\":%llu,\"available_ram_mb\":%llu,"
             "\"has_npu\":%s,\"has_gpu\":%s,"
             "\"battery_capacity_mah\":%u,"
             "\"screen_width\":%u,\"screen_height\":%u}",
             info.device_model, info.device_manufacturer,
             info.os_version, info.cpu_cores,
             info.total_ram_mb, info.available_ram_mb,
             info.has_npu ? "true" : "false",
             info.has_gpu ? "true" : "false",
             info.battery_capacity_mah,
             info.screen_width_px, info.screen_height_px);

    return env->NewStringUTF(json);
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeConnectDaemon(
    JNIEnv* env,
    jclass clazz,
    jstring host,
    jint port,
    jint timeout_ms)
{
    (void)clazz;
    const char* host_str = env->GetStringUTFChars(host, NULL);
    ainos_status_t status = ainos_daemon_connect(host_str, (uint16_t)port, (uint32_t)timeout_ms);
    env->ReleaseStringUTFChars(host, host_str);
    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeSendDaemonCommand(
    JNIEnv* env,
    jclass clazz,
    jint command,
    jbyteArray request_data,
    jbyteArray response_data)
{
    (void)clazz;
    (void)command;

    if (!request_data || !response_data) {
        return (jint)AINOS_ERROR_INVALID_PARAM;
    }

    jsize request_size = env->GetArrayLength(request_data);
    jbyte* request_bytes = env->GetByteArrayElements(request_data, NULL);

    jsize response_capacity = env->GetArrayLength(response_data);
    jbyte* response_bytes = env->GetByteArrayElements(response_data, NULL);

    size_t actual_response_size = (size_t)response_capacity;
    ainos_status_t status = ainos_daemon_send_command(
        (ainos_daemon_command_t)command,
        request_bytes, (size_t)request_size,
        response_bytes, &actual_response_size,
        30000);

    env->ReleaseByteArrayElements(request_data, request_bytes, JNI_ABORT);
    env->ReleaseByteArrayElements(response_data, response_bytes, 0);

    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeStartForegroundService(
    JNIEnv* env,
    jclass clazz,
    jint notification_id,
    jstring channel_id,
    jstring title,
    jstring text)
{
    (void)clazz;

    ainos_foreground_service_config_t config;
    memset(&config, 0, sizeof(config));
    config.notification_id = (int)notification_id;
    config.show_foreground_notification = true;
    config.keep_alive = true;
    config.keep_alive_interval_ms = 30000;

    const char* title_str = env->GetStringUTFChars(title, NULL);
    const char* text_str = env->GetStringUTFChars(text, NULL);
    const char* channel_str = env->GetStringUTFChars(channel_id, NULL);

    strncpy(config.notification_title, title_str, sizeof(config.notification_title) - 1);
    strncpy(config.notification_text, text_str, sizeof(config.notification_text) - 1);
    strncpy(config.channel_id, channel_str, sizeof(config.channel_id) - 1);
    strncpy(config.service_name, "AinosForegroundService", sizeof(config.service_name) - 1);

    ainos_status_t status = ainos_foreground_service_start(&config);

    env->ReleaseStringUTFChars(title, title_str);
    env->ReleaseStringUTFChars(text, text_str);
    env->ReleaseStringUTFChars(channel_id, channel_str);

    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeStopForegroundService(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_foreground_service_stop();
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeShowNotification(
    JNIEnv* env,
    jclass clazz,
    jstring title,
    jstring body,
    jint priority)
{
    (void)clazz;

    ainos_notification_t notif;
    memset(&notif, 0, sizeof(notif));
    strncpy(notif.notification_id, "jni_notification", sizeof(notif.notification_id) - 1);
    strncpy(notif.channel_id, "ainos_default", sizeof(notif.channel_id) - 1);

    const char* title_str = env->GetStringUTFChars(title, NULL);
    const char* body_str = env->GetStringUTFChars(body, NULL);

    strncpy(notif.title, title_str, sizeof(notif.title) - 1);
    strncpy(notif.body, body_str, sizeof(notif.body) - 1);

    env->ReleaseStringUTFChars(title, title_str);
    env->ReleaseStringUTFChars(body, body_str);

    notif.priority = (ainos_notification_priority_t)priority;
    notif.auto_cancel = true;
    notif.show_timestamp = true;
    notif.vibrate = true;
    notif.sound = true;

    return (jint)ainos_notification_show(&notif);
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeModelDownload(
    JNIEnv* env,
    jclass clazz,
    jstring model_id)
{
    (void)clazz;
    const char* model_id_str = env->GetStringUTFChars(model_id, NULL);
    ainos_status_t status = ainos_model_download(model_id_str, NULL, NULL);
    env->ReleaseStringUTFChars(model_id, model_id_str);
    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeModelLoad(
    JNIEnv* env,
    jclass clazz,
    jstring model_id)
{
    (void)clazz;
    const char* model_id_str = env->GetStringUTFChars(model_id, NULL);
    ainos_status_t status = ainos_model_load(model_id_str, NULL, NULL);
    env->ReleaseStringUTFChars(model_id, model_id_str);
    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeModelUnload(
    JNIEnv* env,
    jclass clazz,
    jstring model_id)
{
    (void)clazz;
    const char* model_id_str = env->GetStringUTFChars(model_id, NULL);
    ainos_status_t status = ainos_model_unload(model_id_str);
    env->ReleaseStringUTFChars(model_id, model_id_str);
    return (jint)status;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeRunInference(
    JNIEnv* env,
    jclass clazz,
    jstring model_id,
    jbyteArray input_data,
    jbyteArray output_data)
{
    (void)clazz;
    (void)model_id;
    (void)input_data;
    (void)output_data;

    // This is a simplified stub - actual inference goes through the C API
    return (jint)AINOS_OK;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeRequestPermission(
    JNIEnv* env,
    jclass clazz,
    jint permission)
{
    (void)clazz;
    (void)env;
    return (jint)ainos_permission_request(
        (ainos_permission_t)permission, NULL, NULL);
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeCheckPermission(
    JNIEnv* env,
    jclass clazz,
    jint permission)
{
    (void)env;
    (void)clazz;
    ainos_permission_state_t state;
    ainos_status_t status = ainos_permission_check(
        (ainos_permission_t)permission, &state);
    if (status != AINOS_OK) return (jint)AINOS_PERMISSION_STATE_DENIED;
    return (jint)state;
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeGetPowerMode(
    JNIEnv* env,
    jclass clazz)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_battery_get_power_mode();
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeSetPowerMode(
    JNIEnv* env,
    jclass clazz,
    jint mode)
{
    (void)env;
    (void)clazz;
    return (jint)ainos_battery_request_power_mode((ainos_power_mode_t)mode);
}

JNIEXPORT jint JNICALL
Java_com_ainos_AinosNative_nativeRegisterBackgroundTask(
    JNIEnv* env,
    jclass clazz,
    jstring task_id,
    jstring task_name,
    jint interval_minutes)
{
    (void)clazz;

    ainos_background_task_config_t config;
    memset(&config, 0, sizeof(config));

    const char* task_id_str = env->GetStringUTFChars(task_id, NULL);
    const char* task_name_str = env->GetStringUTFChars(task_name, NULL);

    strncpy(config.task_id, task_id_str, sizeof(config.task_id) - 1);
    strncpy(config.task_name, task_name_str, sizeof(config.task_name) - 1);
    config.interval_minutes = (uint32_t)interval_minutes;
    config.max_execution_time_seconds = 600;
    config.requires_network = true;
    config.max_retries = 3;

    ainos_status_t status = ainos_background_register_task(
        &config, NULL, NULL);

    env->ReleaseStringUTFChars(task_id, task_id_str);
    env->ReleaseStringUTFChars(task_name, task_name_str);

    return (jint)status;
}

} // extern "C"