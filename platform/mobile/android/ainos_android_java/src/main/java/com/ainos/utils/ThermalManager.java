package com.ainos.utils;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.PowerManager;
import android.util.Log;

import com.ainos.AinosNative;

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * ThermalManager - Monitors device thermal conditions and manages
 * thermal-aware throttling for AI inference. Reads from sysfs thermal
 * zones and provides status information.
 */
public class ThermalManager {

    private static final String TAG = "ThermalManager";

    // Thermal status constants
    public static final int STATUS_NORMAL = 0;
    public static final int STATUS_WARM = 1;
    public static final int STATUS_HOT = 2;
    public static final int STATUS_CRITICAL = 3;
    public static final int STATUS_EMERGENCY = 4;
    public static final int STATUS_UNKNOWN = 5;

    // Throttle levels
    public static final int THROTTLE_NONE = 0;
    public static final int THROTTLE_MILD = 1;
    public static final int THROTTLE_MODERATE = 2;
    public static final int THROTTLE_SEVERE = 3;
    public static final int THROTTLE_SHUTDOWN = 4;

    private static final int MONITOR_INTERVAL_MS = 5000;
    private static final float CPU_EMERGENCY_THRESHOLD = 85.0f;
    private static final float CPU_CRITICAL_THRESHOLD = 75.0f;
    private static final float CPU_HOT_THRESHOLD = 65.0f;
    private static final float CPU_WARM_THRESHOLD = 55.0f;
    private static final float BATTERY_EMERGENCY_THRESHOLD = 55.0f;
    private static final float BATTERY_CRITICAL_THRESHOLD = 48.0f;
    private static final float BATTERY_HOT_THRESHOLD = 42.0f;
    private static final float BATTERY_WARM_THRESHOLD = 38.0f;

    // Thermal zone paths for sysfs
    private static final String[] THERMAL_ZONE_PATHS = {
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/thermal/thermal_zone2/temp",
        "/sys/class/thermal/thermal_zone3/temp",
        "/sys/class/thermal/thermal_zone4/temp",
        "/sys/class/thermal/thermal_zone5/temp",
        "/sys/class/thermal/thermal_zone6/temp",
        "/sys/class/thermal/thermal_zone7/temp",
        "/sys/class/thermal/thermal_zone8/temp",
        "/sys/class/thermal/thermal_zone9/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone1/temp",
    };

    private static final String[] BATTERY_TEMP_PATHS = {
        "/sys/class/power_supply/battery/temp",
        "/sys/class/power_supply/Battery/temp",
        "/sys/devices/platform/battery/temp",
    };

    private final Context mContext;
    private final AtomicInteger mCurrentStatus;
    private final AtomicInteger mCurrentThrottle;
    private final ScheduledExecutorService mScheduler;
    private ScheduledFuture<?> mMonitorFuture;
    private ThermalCallback mCallback;
    private boolean mMonitoring;
    private float mMaxCpuTemp;
    private float mMaxBatteryTemp;
    private int mThrottleDurationSeconds;

    /**
     * Callback for thermal state changes.
     */
    public interface ThermalCallback {
        void onThermalStatusChanged(int oldStatus, int newStatus);
        void onTemperatureReading(float cpuTemp, float batteryTemp);
    }

    /**
     * Create the thermal manager.
     */
    public ThermalManager(Context context) {
        mContext = context;
        mCurrentStatus = new AtomicInteger(STATUS_NORMAL);
        mCurrentThrottle = new AtomicInteger(THROTTLE_NONE);
        mScheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "AinosThermalMonitor");
            t.setDaemon(true);
            return t;
        });
        mMaxCpuTemp = 0.0f;
        mMaxBatteryTemp = 0.0f;
        mThrottleDurationSeconds = 0;
    }

    /**
     * Start thermal monitoring.
     */
    public void startMonitoring(ThermalCallback callback) {
        mCallback = callback;
        mMonitoring = true;

        // Register thermal broadcast receiver
        IntentFilter filter = new IntentFilter();
        filter.addAction("android.os.action.THERMAL_EVENT");
        mContext.registerReceiver(mThermalReceiver, filter);

        // Start periodic monitoring
        mMonitorFuture = mScheduler.scheduleAtFixedRate(
            this::checkThermalStatus,
            0,
            MONITOR_INTERVAL_MS,
            TimeUnit.MILLISECONDS);

        Log.i(TAG, "Thermal monitoring started");
    }

    /**
     * Stop thermal monitoring.
     */
    public void stopMonitoring() {
        mMonitoring = false;

        if (mMonitorFuture != null) {
            mMonitorFuture.cancel(false);
            mMonitorFuture = null;
        }

        try {
            mContext.unregisterReceiver(mThermalReceiver);
        } catch (IllegalArgumentException e) {
            // Receiver was not registered
        }

        Log.i(TAG, "Thermal monitoring stopped");
    }

    /**
     * Get the current thermal status.
     */
    public int getCurrentStatus() {
        return mCurrentStatus.get();
    }

    /**
     * Get the current throttle level.
     */
    public int getCurrentThrottle() {
        return mCurrentThrottle.get();
    }

    /**
     * Get the maximum CPU temperature reading.
     */
    public float getMaxCpuTemperature() {
        return mMaxCpuTemp;
    }

    /**
     * Get the maximum battery temperature reading.
     */
    public float getMaxBatteryTemperature() {
        return mMaxBatteryTemp;
    }

    /**
     * Get the duration of throttling in seconds.
     */
    public int getThrottleDurationSeconds() {
        return mThrottleDurationSeconds;
    }

    /**
     * Check if the device is currently throttling.
     */
    public boolean isThrottling() {
        return mCurrentThrottle.get() > THROTTLE_NONE;
    }

    /**
     * Check if inference should be throttled.
     */
    public boolean shouldThrottleInference() {
        return mCurrentStatus.get() >= STATUS_HOT;
    }

    /**
     * Get the recommended batch size based on thermal conditions.
     */
    public int getRecommendedBatchSize() {
        switch (mCurrentStatus.get()) {
            case STATUS_NORMAL: return 8;
            case STATUS_WARM: return 4;
            case STATUS_HOT: return 2;
            case STATUS_CRITICAL:
            case STATUS_EMERGENCY: return 1;
            default: return 4;
        }
    }

    /**
     * Get a human-readable thermal status string.
     */
    public static String getStatusString(int status) {
        switch (status) {
            case STATUS_NORMAL: return "Normal";
            case STATUS_WARM: return "Warm";
            case STATUS_HOT: return "Hot";
            case STATUS_CRITICAL: return "Critical";
            case STATUS_EMERGENCY: return "Emergency";
            default: return "Unknown";
        }
    }

    /**
     * Read CPU temperature from sysfs.
     */
    private float readCpuTemperature() {
        float maxTemp = 0.0f;

        for (String path : THERMAL_ZONE_PATHS) {
            try {
                BufferedReader reader = new BufferedReader(
                    new InputStreamReader(new FileInputStream(path)));
                String line = reader.readLine();
                reader.close();

                if (line != null) {
                    int tempRaw = Integer.parseInt(line.trim());
                    float tempC = tempRaw / 1000.0f;
                    if (tempC > maxTemp) {
                        maxTemp = tempC;
                    }
                }
            } catch (Exception e) {
                // Path may not exist
            }
        }

        return maxTemp;
    }

    /**
     * Read battery temperature from sysfs.
     */
    private float readBatteryTemperature() {
        for (String path : BATTERY_TEMP_PATHS) {
            try {
                BufferedReader reader = new BufferedReader(
                    new InputStreamReader(new FileInputStream(path)));
                String line = reader.readLine();
                reader.close();

                if (line != null) {
                    int tempRaw = Integer.parseInt(line.trim());
                    return tempRaw / 10.0f;
                }
            } catch (Exception e) {
                // Path may not exist
            }
        }
        return -1.0f;
    }

    /**
     * Compute thermal status from temperature readings.
     */
    private int computeStatus(float cpuTemp, float batteryTemp) {
        float maxTemp = Math.max(cpuTemp, batteryTemp);

        if (maxTemp >= CPU_EMERGENCY_THRESHOLD || batteryTemp >= BATTERY_EMERGENCY_THRESHOLD) {
            return STATUS_EMERGENCY;
        }
        if (maxTemp >= CPU_CRITICAL_THRESHOLD || batteryTemp >= BATTERY_CRITICAL_THRESHOLD) {
            return STATUS_CRITICAL;
        }
        if (maxTemp >= CPU_HOT_THRESHOLD || batteryTemp >= BATTERY_HOT_THRESHOLD) {
            return STATUS_HOT;
        }
        if (maxTemp >= CPU_WARM_THRESHOLD || batteryTemp >= BATTERY_WARM_THRESHOLD) {
            return STATUS_WARM;
        }
        return STATUS_NORMAL;
    }

    /**
     * Compute throttle level from temperature.
     */
    private int computeThrottle(float cpuTemp, float batteryTemp) {
        float maxTemp = Math.max(cpuTemp, batteryTemp);

        if (maxTemp >= CPU_EMERGENCY_THRESHOLD) return THROTTLE_SHUTDOWN;
        if (maxTemp >= CPU_CRITICAL_THRESHOLD) return THROTTLE_SEVERE;
        if (maxTemp >= CPU_HOT_THRESHOLD) return THROTTLE_MODERATE;
        if (maxTemp >= CPU_WARM_THRESHOLD) return THROTTLE_MILD;
        return THROTTLE_NONE;
    }

    /**
     * Check thermal status from sysfs.
     */
    private void checkThermalStatus() {
        try {
            float cpuTemp = readCpuTemperature();
            float batteryTemp = readBatteryTemperature();

            if (cpuTemp <= 0.0f) cpuTemp = mMaxCpuTemp;
            if (batteryTemp <= 0.0f) batteryTemp = mMaxBatteryTemp;

            mMaxCpuTemp = cpuTemp;
            mMaxBatteryTemp = batteryTemp;

            int oldStatus = mCurrentStatus.get();
            int newStatus = computeStatus(cpuTemp, batteryTemp);
            int newThrottle = computeThrottle(cpuTemp, batteryTemp);

            mCurrentStatus.set(newStatus);
            mCurrentThrottle.set(newThrottle);

            // Update throttle duration
            if (newThrottle > THROTTLE_NONE) {
                mThrottleDurationSeconds += MONITOR_INTERVAL_MS / 1000;
            } else {
                mThrottleDurationSeconds = 0;
            }

            // Notify callback
            if (oldStatus != newStatus) {
                Log.i(TAG, "Thermal status changed: " + getStatusString(oldStatus) +
                      " -> " + getStatusString(newStatus) +
                      " (CPU=" + String.format("%.1f", cpuTemp) + "C, " +
                      "Battery=" + String.format("%.1f", batteryTemp) + "C)");

                if (mCallback != null) {
                    mCallback.onThermalStatusChanged(oldStatus, newStatus);
                }

                // Update native layer
                AinosNative.nativeGetThermalStatus();
            }

            // Temperature reading callback
            if (mCallback != null && cpuTemp > 0.0f) {
                mCallback.onTemperatureReading(cpuTemp, batteryTemp);
            }

            // Log warning at high temperatures
            if (newStatus >= STATUS_HOT) {
                Log.w(TAG, "Thermal warning: " + getStatusString(newStatus) +
                      " CPU=" + String.format("%.1f", cpuTemp) + "C");
            }

        } catch (Exception e) {
            Log.e(TAG, "Thermal check failed", e);
        }
    }

    /**
     * Handle Android thermal event broadcast.
     */
    private final android.content.BroadcastReceiver mThermalReceiver =
        new android.content.BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (intent == null) return;

                if ("android.os.action.THERMAL_EVENT".equals(intent.getAction())) {
                    int thermalEvent = intent.getIntExtra(
                        "android.os.extra.THERMAL_EVENT", -1);
                    if (thermalEvent >= 0) {
                        Log.i(TAG, "Thermal event received: " + thermalEvent);
                        // Trigger immediate check
                        checkThermalStatus();
                    }
                }
            }
        };
}