package com.ainos;

import android.util.Log;

/**
 * AinosNative - JNI bridge class for native C/C++ functions.
 * Provides the interface between Java code and the native Ainos platform layer.
 */
public class AinosNative {

    private static final String TAG = "AinosNative";
    private static boolean sLoaded = false;

    static {
        try {
            System.loadLibrary("ainos_android");
            sLoaded = true;
            Log.i(TAG, "Native library loaded successfully");
        } catch (UnsatisfiedLinkError e) {
            Log.e(TAG, "Failed to load native library: " + e.getMessage());
            sLoaded = false;
        }
    }

    /**
     * Check if the native library is loaded.
     */
    public static boolean isLoaded() {
        return sLoaded;
    }

    /**
     * Initialize the Ainos platform.
     *
     * @param appName    Application name
     * @param appVersion Application version
     * @return 0 on success, negative error code on failure
     */
    public static native int nativeInit(String appName, String appVersion);

    /**
     * Shutdown the Ainos platform.
     */
    public static native void nativeShutdown();

    /**
     * Get the Android API level.
     *
     * @return API level (e.g., 33 for Android 13)
     */
    public static native int nativeGetApiLevel();

    /**
     * Get the current thermal status.
     *
     * @return 0=Normal, 1=Warm, 2=Hot, 3=Critical, 4=Emergency
     */
    public static native int nativeGetThermalStatus();

    /**
     * Get the current battery level.
     *
     * @return Battery percentage (0-100)
     */
    public static native int nativeGetBatteryLevel();

    /**
     * Check if the device is currently charging.
     *
     * @return true if charging
     */
    public static native boolean nativeIsCharging();

    /**
     * Get device information as JSON string.
     *
     * @return JSON string with device info
     */
    public static native String nativeGetDeviceInfo();

    /**
     * Connect to the AinosOS daemon.
     *
     * @param host      Daemon host address
     * @param port      Daemon port
     * @param timeoutMs Connection timeout in milliseconds
     * @return 0 on success
     */
    public static native int nativeConnectDaemon(String host, int port, int timeoutMs);

    /**
     * Send a command to the daemon and receive response.
     *
     * @param command      Command code
     * @param requestData  Request payload bytes
     * @param responseData Buffer for response bytes
     * @return 0 on success
     */
    public static native int nativeSendDaemonCommand(int command, byte[] requestData, byte[] responseData);

    /**
     * Start the foreground service.
     *
     * @param notificationId  Notification ID for the foreground notification
     * @param channelId       Notification channel ID
     * @param title           Notification title
     * @param text            Notification text
     * @return 0 on success
     */
    public static native int nativeStartForegroundService(
        int notificationId, String channelId, String title, String text);

    /**
     * Stop the foreground service.
     *
     * @return 0 on success
     */
    public static native int nativeStopForegroundService();

    /**
     * Show a notification.
     *
     * @param title    Notification title
     * @param body     Notification body
     * @param priority Notification priority (0-4)
     * @return 0 on success
     */
    public static native int nativeShowNotification(String title, String body, int priority);

    /**
     * Start downloading a model.
     *
     * @param modelId Model identifier
     * @return 0 on success
     */
    public static native int nativeModelDownload(String modelId);

    /**
     * Load a model into memory.
     *
     * @param modelId Model identifier
     * @return 0 on success
     */
    public static native int nativeModelLoad(String modelId);

    /**
     * Unload a model from memory.
     *
     * @param modelId Model identifier
     * @return 0 on success
     */
    public static native int nativeModelUnload(String modelId);

    /**
     * Run inference on a model.
     *
     * @param modelId    Model identifier
     * @param inputData  Input tensor data
     * @param outputData Output tensor buffer
     * @return 0 on success
     */
    public static native int nativeRunInference(
        String modelId, byte[] inputData, byte[] outputData);

    /**
     * Request a permission from the system.
     *
     * @param permission Permission code
     * @return 0 on success
     */
    public static native int nativeRequestPermission(int permission);

    /**
     * Check the state of a permission.
     *
     * @param permission Permission code
     * @return 0=Not determined, 1=Granted, 2=Denied, 3=Restricted
     */
    public static native int nativeCheckPermission(int permission);

    /**
     * Get the current power mode.
     *
     * @return 0=Normal, 1=Low power, 2=Ultra saving, 3=Performance
     */
    public static native int nativeGetPowerMode();

    /**
     * Set the power mode.
     *
     * @param mode Power mode code
     * @return 0 on success
     */
    public static native int nativeSetPowerMode(int mode);

    /**
     * Register a background task.
     *
     * @param taskId          Task identifier
     * @param taskName        Task display name
     * @param intervalMinutes Task interval in minutes
     * @return 0 on success
     */
    public static native int nativeRegisterBackgroundTask(
        String taskId, String taskName, int intervalMinutes);

    /**
     * Native error codes matching C API.
     */
    public static class Error {
        public static final int OK = 0;
        public static final int GENERAL = -1;
        public static final int INVALID_PARAM = -2;
        public static final int OUT_OF_MEMORY = -3;
        public static final int NOT_INITIALIZED = -4;
        public static final int ALREADY_INITIALIZED = -5;
        public static final int TIMEOUT = -6;
        public static final int NETWORK = -7;
        public static final int PERMISSION_DENIED = -8;
        public static final int THERMAL_THROTTLED = -9;
        public static final int BATTERY_LOW = -10;
        public static final int MODEL_NOT_FOUND = -11;
        public static final int MODEL_LOAD_FAILED = -12;
        public static final int MODEL_INVALID = -13;
        public static final int INFERENCE_FAILED = -14;
        public static final int DAEMON_UNREACHABLE = -15;
        public static final int DAEMON_DISCONNECTED = -16;
        public static final int STREAM_BUSY = -17;
        public static final int STREAM_CLOSED = -18;
        public static final int NOT_SUPPORTED = -19;
        public static final int BUSY = -20;
        public static final int CANCELLED = -21;
        public static final int STORAGE_FULL = -22;
        public static final int UPDATE_AVAILABLE = -23;
        public static final int NEEDS_REBOOT = -24;

        /**
         * Get a human-readable error message.
         */
        public static String toString(int errorCode) {
            switch (errorCode) {
                case OK: return "OK";
                case GENERAL: return "General error";
                case INVALID_PARAM: return "Invalid parameter";
                case OUT_OF_MEMORY: return "Out of memory";
                case NOT_INITIALIZED: return "Not initialized";
                case ALREADY_INITIALIZED: return "Already initialized";
                case TIMEOUT: return "Timeout";
                case NETWORK: return "Network error";
                case PERMISSION_DENIED: return "Permission denied";
                case THERMAL_THROTTLED: return "Thermal throttled";
                case BATTERY_LOW: return "Battery low";
                case MODEL_NOT_FOUND: return "Model not found";
                case MODEL_LOAD_FAILED: return "Model load failed";
                case MODEL_INVALID: return "Model invalid";
                case INFERENCE_FAILED: return "Inference failed";
                case DAEMON_UNREACHABLE: return "Daemon unreachable";
                case DAEMON_DISCONNECTED: return "Daemon disconnected";
                case STREAM_BUSY: return "Stream busy";
                case STREAM_CLOSED: return "Stream closed";
                case NOT_SUPPORTED: return "Not supported";
                case BUSY: return "Busy";
                case CANCELLED: return "Cancelled";
                case STORAGE_FULL: return "Storage full";
                case UPDATE_AVAILABLE: return "Update available";
                case NEEDS_REBOOT: return "Needs reboot";
                default: return "Unknown error (" + errorCode + ")";
            }
        }
    }

    /**
     * Permission codes matching C API.
     */
    public static class Permission {
        public static final int CAMERA = 0;
        public static final int MICROPHONE = 1;
        public static final int STORAGE = 2;
        public static final int NOTIFICATIONS = 3;
        public static final int BACKGROUND_SERVICE = 4;
        public static final int NETWORK_STATE = 5;
        public static final int BLUETOOTH = 6;
        public static final int LOCATION = 7;
        public static final int VIBRATE = 8;
        public static final int WAKE_LOCK = 9;
        public static final int FOREGROUND_SERVICE = 10;
        public static final int SCHEDULE_EXACT_ALARM = 11;
        public static final int POST_NOTIFICATIONS = 12;

        /**
         * Get the display name for a permission code.
         */
        public static String getName(int permission) {
            switch (permission) {
                case CAMERA: return "Camera";
                case MICROPHONE: return "Microphone";
                case STORAGE: return "Storage";
                case NOTIFICATIONS: return "Notifications";
                case BACKGROUND_SERVICE: return "Background Service";
                case NETWORK_STATE: return "Network State";
                case BLUETOOTH: return "Bluetooth";
                case LOCATION: return "Location";
                case VIBRATE: return "Vibrate";
                case WAKE_LOCK: return "Wake Lock";
                case FOREGROUND_SERVICE: return "Foreground Service";
                case SCHEDULE_EXACT_ALARM: return "Schedule Exact Alarm";
                case POST_NOTIFICATIONS: return "Post Notifications";
                default: return "Unknown";
            }
        }
    }

    /**
     * Thermal status codes.
     */
    public static class ThermalStatus {
        public static final int NORMAL = 0;
        public static final int WARM = 1;
        public static final int HOT = 2;
        public static final int CRITICAL = 3;
        public static final int EMERGENCY = 4;
        public static final int UNKNOWN = 5;

        public static String toString(int status) {
            switch (status) {
                case NORMAL: return "Normal";
                case WARM: return "Warm";
                case HOT: return "Hot";
                case CRITICAL: return "Critical";
                case EMERGENCY: return "Emergency";
                default: return "Unknown";
            }
        }
    }

    /**
     * Power mode codes.
     */
    public static class PowerMode {
        public static final int NORMAL = 0;
        public static final int LOW_POWER = 1;
        public static final int ULTRA_SAVING = 2;
        public static final int PERFORMANCE = 3;
    }

    /**
     * Daemon command codes.
     */
    public static class DaemonCommand {
        public static final int HEARTBEAT = 0x0001;
        public static final int GET_STATUS = 0x0002;
        public static final int REGISTER_CLIENT = 0x0003;
        public static final int UNREGISTER_CLIENT = 0x0004;
        public static final int MODEL_LIST = 0x0010;
        public static final int MODEL_DOWNLOAD = 0x0011;
        public static final int MODEL_DELETE = 0x0012;
        public static final int INFERENCE = 0x0020;
        public static final int INFERENCE_STREAM = 0x0021;
        public static final int CANCEL = 0x0022;
        public static final int SYSTEM_UPDATE = 0x0030;
        public static final int GET_LOGS = 0x0031;
        public static final int RESTART = 0x0032;
        public static final int SHUTDOWN = 0x0033;
        public static final int PUSH_NOTIFICATION = 0x0040;
        public static final int THERMAL_STATUS = 0x0050;
        public static final int BATTERY_STATUS = 0x0051;
        public static final int DEVICE_INFO = 0x0060;
    }
}