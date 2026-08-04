# Ainos Mobile Platform Support Layer

## Overview

The Ainos Mobile Platform Support Layer provides a unified API for Android and iOS platforms to support AI inference, thermal management, battery optimization, daemon communication, and background services. It is the mobile counterpart to the AinosOS daemon, enabling seamless on-device AI capabilities.

## Architecture

```
platform/mobile/
├── include/ainos/platform_mobile.h   # Common C API header
├── common/                           # Shared C implementation
│   ├── ainos_mobile_common.h
│   └── ainos_mobile_common.c
├── android/                          # Android-specific implementation
│   ├── CMakeLists.txt                # Native build configuration
│   ├── ainos_android_java/           # Java/JNI layer
│   │   ├── src/main/java/com/ainos/
│   │   │   ├── AinosService.java     # Foreground service
│   │   │   ├── AinosNative.java      # JNI bridge
│   │   │   ├── AinosBroadcastReceiver.java
│   │   │   ├── models/               # Data models
│   │   │   ├── inference/            # Inference engine
│   │   │   └── utils/                # Utilities
│   │   ├── AndroidManifest.xml
│   │   └── res/                      # Resources
│   └── cpp/                          # Native C++ implementation
│       ├── ainos_android_platform.cpp
│       ├── ainos_android_thermal.cpp
│       ├── ainos_android_nn.cpp
│       └── ainos_android_jni.cpp
├── ios/                              # iOS-specific implementation
│   ├── CMakeLists.txt
│   ├── AinosPlatform/                # Swift platform layer
│   │   ├── AinosPlatform.swift
│   │   ├── AinosCoreML.swift
│   │   ├── AinosNeuralEngine.swift
│   │   ├── AinosThermal.swift
│   │   ├── AinosBackground.swift
│   │   └── AinosBattery.swift
│   ├── AinosPlatform.h               # Obj-C bridging header
│   └── Info.plist
├── tests/                            # Platform tests
│   ├── test_android.cpp
│   └── test_ios.swift
└── README.md                         # This file
```

## Features

### 1. Android Background Service + Foreground Notification
- `AinosService.java` implements a long-running foreground service with persistent notification
- Automatic restart on crash (START_STICKY)
- Wake lock acquisition for long-running tasks
- Heartbeat to daemon at configurable intervals

### 2. iOS Background Tasks + Extensions
- `AinosBackground.swift` manages BGTaskScheduler registration
- Supports model download, inference, sync, maintenance, and update check tasks
- Automatic resubmission after completion

### 3. Mobile AI Inference Engine
- **Android**: NNAPI (API 27+), GPU delegate, XNNPACK acceleration
- **iOS**: CoreML, Apple Neural Engine (ANE, A12+), Metal GPU
- Automatic backend selection based on hardware capabilities
- Thermal-aware scheduling and batch size adjustment

### 4. Thermal Management
- Monitors CPU and battery temperatures via sysfs (Android) and ProcessInfo (iOS)
- Multi-level thermal status: Normal, Warm, Hot, Critical, Emergency
- Automatic CPU frequency scaling on Android
- Inference throttling when device overheats

### 5. Battery Management
- Real-time battery level, charging status, and temperature monitoring
- Low power mode detection and adaptation
- Estimated remaining time calculation
- Power mode control (Normal, Low Power, Ultra Saving, Performance)

### 6. Permission Management
- Unified permission model across Android and iOS
- Support for Camera, Microphone, Storage, Notifications, Bluetooth, etc.
- Rationale display and settings redirection

### 7. Model Download/Cache Management
- Built-in model registry with 8 default models (LLM, Vision, Embedding, Audio)
- Download, pause, resume, cancel operations
- Cache size management with LRU eviction
- SHA-256 checksum verification

### 8. Daemon Communication (TCP/HTTP)
- Two-way communication with AinosOS daemon
- Message format: 12-byte header + payload
- Automatic reconnection with exponential backoff
- Heartbeat monitoring

### 9. Mobile Streaming Inference
- Token-by-token generation for LLM text generation
- Concurrent stream support (up to 4 streams)
- Thermal-aware pacing during streaming
- Stream timeout and cancellation

### 10. Push Notifications
- Notification channel creation and management
- Priority-based notification display
- Scheduled notifications for future delivery
- Action callbacks for notification interactions

## Build Instructions

### Android

```bash
# Build native library
cd platform/mobile/android
mkdir build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
         -DANDROID_ABI=arm64-v8a \
         -DANDROID_PLATFORM=android-24
make -j$(nproc)

# Build Java layer (via Gradle)
./gradlew :ainos_android_java:assembleRelease
```

### iOS

```bash
# Build framework
cd platform/mobile/ios
mkdir build && cd build
cmake .. -G Xcode -DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0
xcodebuild -project AinosPlatform.xcodeproj -scheme AinosPlatform -sdk iphoneos
```

## Usage

### C API (Android/iOS native)

```c
#include "ainos/platform_mobile.h"

// Initialize
ainos_platform_init("MyApp", "1.0.0", NULL);

// Check thermal
ainos_thermal_status_t thermal = ainos_thermal_get_status();

// Get battery
int level;
ainos_battery_get_level(&level);

// Connect to daemon
ainos_daemon_connect("127.0.0.1", 8732, 5000);

// Load and run model
ainos_model_load("ainos-llm-7b-q4", NULL, NULL);
ainos_tensor_t input = { ... };
ainos_tensor_t* output = NULL;
ainos_inference_run("ainos-llm-7b-q4", &input, &output);

// Cleanup
ainos_platform_shutdown();
```

### Android Java API

```java
// Start foreground service
Intent intent = new Intent(context, AinosService.class);
intent.setAction("com.ainos.action.START_FOREGROUND");
context.startForegroundService(intent);

// Get service instance
AinosService service = AinosService.getInstance();

// Run inference
ModelInfo model = new ModelInfo("ainos-llm-7b-q4", "LLM", ModelInfo.FORMAT_TFLITE);
InferenceResult result = service.getInferenceEngine().runInference(model, inputData);
```

### iOS Swift API

```swift
// Initialize platform
AinosPlatform.shared.initialize(appName: "MyApp", appVersion: "1.0.0") { status in
    // Check thermal state
    let thermal = AinosPlatform.shared.getThermalStatus()

    // Get battery level
    let level = AinosPlatform.shared.getBatteryLevel()

    // Connect to daemon
    AinosPlatform.shared.connectDaemon(host: "127.0.0.1", port: 8732, timeout: 5000) { status in
        // Connected
    }
}
```

## API Reference

See `include/ainos/platform_mobile.h` for the complete C API reference.

## Version History

- 1.0.0 - Initial release with Android and iOS support

## License

Copyright (c) Ainos 2026. All rights reserved.