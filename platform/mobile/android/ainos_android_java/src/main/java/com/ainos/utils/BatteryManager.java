package com.ainos.utils;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.util.Log;

/**
 * BatteryManager - Monitors battery state and provides power management
 * for the Ainos platform. Supports low-power mode adaptation and
 * charging state detection.
 */
public class BatteryManager {

    private static final String TAG = "BatteryManager";

    private final Context mContext;
    private final android.os.BatteryManager mBatteryManager;
    private BatteryCallback mCallback;
    private boolean mMonitoring;
    private int mLastLevel;
    private boolean mLastCharging;
    private int mLastTemperature;

    /**
     * Callback for battery state changes.
     */
    public interface BatteryCallback {
        void onBatteryLevelChanged(int level);
        void onChargingStatusChanged(boolean isCharging);
    }

    /**
     * Create the battery manager.
     */
    public BatteryManager(Context context) {
        mContext = context;
        mBatteryManager = (android.os.BatteryManager)
            context.getSystemService(Context.BATTERY_SERVICE);
        mLastLevel = getCurrentLevel();
        mLastCharging = isCharging();
        mLastTemperature = 0;
    }

    /**
     * Start monitoring battery state.
     */
    public void startMonitoring(BatteryCallback callback) {
        mCallback = callback;
        mMonitoring = true;

        // Register battery broadcast receiver
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_BATTERY_CHANGED);
        filter.addAction(Intent.ACTION_BATTERY_LOW);
        filter.addAction(Intent.ACTION_BATTERY_OKAY);
        filter.addAction(Intent.ACTION_POWER_CONNECTED);
        filter.addAction(Intent.ACTION_POWER_DISCONNECTED);

        mContext.registerReceiver(mBatteryReceiver, filter);

        Log.i(TAG, "Battery monitoring started");
    }

    /**
     * Stop monitoring battery state.
     */
    public void stopMonitoring() {
        mMonitoring = false;
        try {
            mContext.unregisterReceiver(mBatteryReceiver);
        } catch (IllegalArgumentException e) {
            // Receiver was not registered
        }
        Log.i(TAG, "Battery monitoring stopped");
    }

    /**
     * Get the current battery level (0-100).
     */
    public int getCurrentLevel() {
        if (mBatteryManager != null) {
            return mBatteryManager.getIntProperty(
                android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY);
        }
        return -1;
    }

    /**
     * Check if the device is currently charging.
     */
    public boolean isCharging() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        Intent batteryStatus = mContext.registerReceiver(null, filter);
        if (batteryStatus != null) {
            int status = batteryStatus.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
            return status == BatteryManager.BATTERY_STATUS_CHARGING ||
                   status == BatteryManager.BATTERY_STATUS_FULL;
        }
        return false;
    }

    /**
     * Get the current battery temperature in Celsius.
     */
    public float getTemperature() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        Intent batteryStatus = mContext.registerReceiver(null, filter);
        if (batteryStatus != null) {
            int temp = batteryStatus.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1);
            if (temp >= 0) {
                return temp / 10.0f;
            }
        }
        return -1.0f;
    }

    /**
     * Get the battery health status.
     */
    public int getHealth() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        Intent batteryStatus = mContext.registerReceiver(null, filter);
        if (batteryStatus != null) {
            return batteryStatus.getIntExtra(BatteryManager.EXTRA_HEALTH, -1);
        }
        return -1;
    }

    /**
     * Get the battery technology (e.g., "Li-ion").
     */
    public String getTechnology() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        Intent batteryStatus = mContext.registerReceiver(null, filter);
        if (batteryStatus != null) {
            return batteryStatus.getStringExtra(BatteryManager.EXTRA_TECHNOLOGY);
        }
        return "Unknown";
    }

    /**
     * Get the battery voltage in volts.
     */
    public float getVoltage() {
        IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
        Intent batteryStatus = mContext.registerReceiver(null, filter);
        if (batteryStatus != null) {
            int voltage = batteryStatus.getIntExtra(BatteryManager.EXTRA_VOLTAGE, -1);
            if (voltage > 0) {
                return voltage / 1000.0f;
            }
        }
        return -1.0f;
    }

    /**
     * Check if the battery is in a low state (<= 20%).
     */
    public boolean isLow() {
        int level = getCurrentLevel();
        return level >= 0 && level <= 20;
    }

    /**
     * Check if the battery is critically low (<= 10%).
     */
    public boolean isCriticallyLow() {
        int level = getCurrentLevel();
        return level >= 0 && level <= 10;
    }

    /**
     * Check if the battery is healthy.
     */
    public boolean isHealthy() {
        int health = getHealth();
        return health == BatteryManager.BATTERY_HEALTH_GOOD ||
               health == BatteryManager.BATTERY_HEALTH_OVERHEAT;
    }

    /**
     * Get the estimated remaining battery life in minutes.
     */
    public int getEstimatedRemainingMinutes() {
        int level = getCurrentLevel();
        if (level < 0) return -1;

        if (isCharging()) {
            // Estimate time to full: ~1.5 min per percent
            return (100 - level) * 90 / 100;
        } else {
            // Estimate time remaining: ~2 min per percent
            return level * 2;
        }
    }

    /**
     * Check if the device is in power save mode.
     */
    public boolean isPowerSaveMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            PowerManager powerManager = (PowerManager) mContext
                .getSystemService(Context.POWER_SERVICE);
            if (powerManager != null) {
                return powerManager.isPowerSaveMode();
            }
        }
        return false;
    }

    /**
     * Get a human-readable health string.
     */
    public static String getHealthString(int health) {
        switch (health) {
            case BatteryManager.BATTERY_HEALTH_COLD: return "Cold";
            case BatteryManager.BATTERY_HEALTH_DEAD: return "Dead";
            case BatteryManager.BATTERY_HEALTH_GOOD: return "Good";
            case BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE: return "Over Voltage";
            case BatteryManager.BATTERY_HEALTH_OVERHEAT: return "Overheat";
            case BatteryManager.BATTERY_HEALTH_UNSPECIFIED_FAILURE: return "Failure";
            case BatteryManager.BATTERY_HEALTH_UNKNOWN: return "Unknown";
            default: return "Unknown";
        }
    }

    /**
     * Get a summary of battery state.
     */
    public String getBatterySummary() {
        int level = getCurrentLevel();
        boolean charging = isCharging();
        float temp = getTemperature();
        float voltage = getVoltage();

        return String.format(
            "Battery: %d%% %s, %.1fC, %.2fV, %s",
            level,
            charging ? "charging" : "discharging",
            temp,
            voltage,
            isLow() ? "LOW" : "OK");
    }

    /**
     * Get the current battery level (cached).
     */
    public int getLastLevel() {
        return mLastLevel;
    }

    /**
     * Check if the device was last known to be charging.
     */
    public boolean getLastCharging() {
        return mLastCharging;
    }

    /**
     * Get the last battery temperature reading.
     */
    public int getLastTemperature() {
        return mLastTemperature;
    }

    // Broadcast receiver for battery state changes
    private final android.content.BroadcastReceiver mBatteryReceiver =
        new android.content.BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (intent == null) return;

                String action = intent.getAction();
                if (action == null) return;

                switch (action) {
                    case Intent.ACTION_BATTERY_CHANGED: {
                        int level = intent.getIntExtra(
                            BatteryManager.EXTRA_LEVEL, -1);
                        int scale = intent.getIntExtra(
                            BatteryManager.EXTRA_SCALE, -1);
                        int status = intent.getIntExtra(
                            BatteryManager.EXTRA_STATUS, -1);
                        int temperature = intent.getIntExtra(
                            BatteryManager.EXTRA_TEMPERATURE, -1);

                        if (level >= 0 && scale > 0) {
                            int batteryPercent = level * 100 / scale;
                            boolean isCharging = (status == BatteryManager.BATTERY_STATUS_CHARGING ||
                                                  status == BatteryManager.BATTERY_STATUS_FULL);

                            mLastTemperature = temperature;

                            // Notify level change
                            if (batteryPercent != mLastLevel && mCallback != null) {
                                mCallback.onBatteryLevelChanged(batteryPercent);
                            }

                            // Notify charging change
                            if (isCharging != mLastCharging && mCallback != null) {
                                mCallback.onChargingStatusChanged(isCharging);
                            }

                            mLastLevel = batteryPercent;
                            mLastCharging = isCharging;
                        }
                        break;
                    }

                    case Intent.ACTION_BATTERY_LOW: {
                        Log.w(TAG, "Battery low!");
                        if (mCallback != null) {
                            mCallback.onBatteryLevelChanged(mLastLevel);
                        }
                        break;
                    }

                    case Intent.ACTION_POWER_CONNECTED: {
                        Log.i(TAG, "Power connected");
                        if (mCallback != null) {
                            mCallback.onChargingStatusChanged(true);
                        }
                        mLastCharging = true;
                        break;
                    }

                    case Intent.ACTION_POWER_DISCONNECTED: {
                        Log.i(TAG, "Power disconnected");
                        if (mCallback != null) {
                            mCallback.onChargingStatusChanged(false);
                        }
                        mLastCharging = false;
                        break;
                    }
                }
            }
        };
}