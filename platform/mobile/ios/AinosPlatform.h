/**
 * AinosPlatform.h
 * Objective-C bridging header for Ainos iOS platform
 *
 * Copyright (c) Ainos 2026
 */

#ifndef AinosPlatform_h
#define AinosPlatform_h

#import <Foundation/Foundation.h>

// Error codes matching C API
typedef NS_ENUM(NSInteger, AinosStatus) {
    AinosStatusOk = 0,
    AinosStatusGeneral = -1,
    AinosStatusInvalidParam = -2,
    AinosStatusOutOfMemory = -3,
    AinosStatusNotInitialized = -4,
    AinosStatusAlreadyInitialized = -5,
    AinosStatusTimeout = -6,
    AinosStatusNetwork = -7,
    AinosStatusPermissionDenied = -8,
    AinosStatusThermalThrottled = -9,
    AinosStatusBatteryLow = -10,
    AinosStatusModelNotFound = -11,
    AinosStatusModelLoadFailed = -12,
    AinosStatusModelInvalid = -13,
    AinosStatusInferenceFailed = -14,
    AinosStatusDaemonUnreachable = -15,
    AinosStatusDaemonDisconnected = -16,
    AinosStatusStreamBusy = -17,
    AinosStatusStreamClosed = -18,
    AinosStatusNotSupported = -19,
    AinosStatusBusy = -20,
    AinosStatusCancelled = -21,
    AinosStatusStorageFull = -22,
    AinosStatusUpdateAvailable = -23,
    AinosStatusNeedsReboot = -24
};

// Thermal status
typedef NS_ENUM(NSInteger, AinosThermalStatus) {
    AinosThermalNormal = 0,
    AinosThermalWarm = 1,
    AinosThermalHot = 2,
    AinosThermalCritical = 3,
    AinosThermalEmergency = 4,
    AinosThermalUnknown = 5
};

// Battery status
typedef NS_ENUM(NSInteger, AinosBatteryStatus) {
    AinosBatteryUnknown = 0,
    AinosBatteryCharging = 1,
    AinosBatteryDischarging = 2,
    AinosBatteryFull = 3,
    AinosBatteryNotCharging = 4
};

// Power mode
typedef NS_ENUM(NSInteger, AinosPowerMode) {
    AinosPowerModeNormal = 0,
    AinosPowerModeLowPower = 1,
    AinosPowerModeUltraSaving = 2,
    AinosPowerModePerformance = 3
};

// Backend types
typedef NS_ENUM(NSInteger, AinosInferenceBackend) {
    AinosInferenceBackendAuto = 0,
    AinosInferenceBackendCPU = 1,
    AinosInferenceBackendGPU = 2,
    AinosInferenceBackendCoreML = 4,
    AinosInferenceBackendANE = 5
};

// Model format
typedef NS_ENUM(NSInteger, AinosModelFormat) {
    AinosModelFormatUnknown = 0,
    AinosModelFormatTFLite = 1,
    AinosModelFormatCoreML = 2,
    AinosModelFormatONNX = 3,
    AinosModelFormatSafeTensors = 4
};

// Model type
typedef NS_ENUM(NSInteger, AinosModelType) {
    AinosModelTypeUnknown = 0,
    AinosModelTypeLLM = 1,
    AinosModelTypeVision = 2,
    AinosModelTypeAudio = 3,
    AinosModelTypeEmbedding = 4,
    AinosModelTypeMultimodal = 5
};

// Model state
typedef NS_ENUM(NSInteger, AinosModelState) {
    AinosModelStateNotDownloaded = 0,
    AinosModelStateDownloading = 1,
    AinosModelStateDownloaded = 2,
    AinosModelStateLoading = 3,
    AinosModelStateLoaded = 4,
    AinosModelStateError = 5,
    AinosModelStateObsolete = 6
};

// Precision
typedef NS_ENUM(NSInteger, AinosModelPrecision) {
    AinosModelPrecisionFP32 = 0,
    AinosModelPrecisionFP16 = 1,
    AinosModelPrecisionINT8 = 2,
    AinosModelPrecisionINT4 = 3,
    AinosModelPrecisionMixed = 4
};

// Background task type
typedef NS_ENUM(NSInteger, AinosBackgroundTaskType) {
    AinosBackgroundTaskDownload = 0,
    AinosBackgroundTaskInference = 1,
    AinosBackgroundTaskSync = 2,
    AinosBackgroundTaskMaintenance = 3,
    AinosBackgroundTaskUpdateCheck = 4
};

#endif /* AinosPlatform_h */