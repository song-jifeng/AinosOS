package com.ainos;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.BatteryManager;
import android.os.Build;
import android.util.Log;

/**
 * AinosBroadcastReceiver - Handles system broadcast events for the Ainos platform.
 * Monitors battery state, connectivity changes, power state, and boot events.
 */
public class AinosBroadcastReceiver extends BroadcastReceiver {

    private static final String TAG = "AinosBroadcastReceiver";

    public interface BatteryStateListener {
        void onBatteryChanged(int level, boolean isCharging, int temperature);
        void onPowerConnected();
        void onPowerDisconnected();
        void onLowBattery();
    }

    public interface ConnectivityListener {
        void onNetworkAvailable();
        void onNetworkLost();
    }

    public interface BootListener {
        void onBootCompleted();
    }

    private BatteryStateListener mBatteryListener;
    private ConnectivityListener mConnectivityListener;
    private BootListener mBootListener;

    private static int sLastBatteryLevel = -1;
    private static boolean sLastChargingState = false;

    public void setBatteryStateListener(BatteryStateListener listener) {
        mBatteryListener = listener;
    }

    public void setConnectivityListener(ConnectivityListener listener) {
        mConnectivityListener = listener;
    }

    public void setBootListener(BootListener listener) {
        mBootListener = listener;
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) {
            return;
        }

        String action = intent.getAction();
        Log.d(TAG, "Broadcast received: " + action);

        switch (action) {
            case Intent.ACTION_BATTERY_CHANGED:
                handleBatteryChanged(intent);
                break;

            case Intent.ACTION_BATTERY_LOW:
                handleBatteryLow();
                break;

            case Intent.ACTION_BATTERY_OKAY:
                handleBatteryOkay();
                break;

            case Intent.ACTION_POWER_CONNECTED:
                handlePowerConnected(intent);
                break;

            case Intent.ACTION_POWER_DISCONNECTED:
                handlePowerDisconnected();
                break;

            case Intent.ACTION_BOOT_COMPLETED:
                handleBootCompleted();
                break;

            case Intent.ACTION_SHUTDOWN:
                handleShutdown();
                break;

            case Intent.ACTION_REBOOT:
                handleReboot();
                break;

            case Intent.ACTION_SCREEN_ON:
                handleScreenOn();
                break;

            case Intent.ACTION_SCREEN_OFF:
                handleScreenOff();
                break;

            case Intent.ACTION_USER_PRESENT:
                handleUserPresent();
                break;

            case Intent.ACTION_TIME_TICK:
                // Periodic tick - can be used for lightweight monitoring
                break;

            case Intent.ACTION_TIME_CHANGED:
                handleTimeChanged();
                break;

            case Intent.ACTION_TIMEZONE_CHANGED:
                handleTimezoneChanged();
                break;

            case Intent.ACTION_LOCALE_CHANGED:
                handleLocaleChanged();
                break;

            case "android.os.action.DEVICE_IDLE_MODE_CHANGED":
                handleIdleModeChanged(intent);
                break;

            case "android.os.action.POWER_SAVE_MODE_CHANGED":
                handlePowerSaveModeChanged(intent);
                break;

            case "android.intent.action.ACTION_IDLE_MAINTENANCE_START":
                handleIdleMaintenanceStart();
                break;

            case "android.intent.action.ACTION_IDLE_MAINTENANCE_END":
                handleIdleMaintenanceEnd();
                break;

            default:
                Log.d(TAG, "Unhandled broadcast: " + action);
        }
    }

    private void handleBatteryChanged(Intent intent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            int level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
            int scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
            int status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
            int temperature = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1);
            int plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1);

            if (level >= 0 && scale > 0) {
                int batteryPercent = level * 100 / scale;
                boolean isCharging = (status == BatteryManager.BATTERY_STATUS_CHARGING ||
                                      status == BatteryManager.BATTERY_STATUS_FULL);
                float tempCelsius = temperature / 10.0f;

                // Log significant changes
                if (batteryPercent != sLastBatteryLevel || isCharging != sLastChargingState) {
                    Log.i(TAG, "Battery: " + batteryPercent + "% " +
                          (isCharging ? "charging" : "discharging") +
                          " temp=" + tempCelsius + "C");

                    sLastBatteryLevel = batteryPercent;
                    sLastChargingState = isCharging;

                    // Notify native layer
                    AinosNative.nativeGetBatteryLevel(); // updates internal state
                }

                if (mBatteryListener != null) {
                    mBatteryListener.onBatteryChanged(batteryPercent, isCharging, (int)tempCelsius);
                }
            }
        }
    }

    private void handleBatteryLow() {
        Log.w(TAG, "Battery low warning received");
        if (mBatteryListener != null) {
            mBatteryListener.onLowBattery();
        }

        // Try to start AinosService if it's not running
        Intent serviceIntent = new Intent();
        serviceIntent.setClassName("com.ainos", "com.ainos.AinosService");
        serviceIntent.setAction("com.ainos.action.START_FOREGROUND");
        try {
            getContext().startService(serviceIntent);
        } catch (Exception e) {
            Log.e(TAG, "Failed to start service on low battery", e);
        }
    }

    private void handleBatteryOkay() {
        Log.i(TAG, "Battery okay again");
    }

    private void handlePowerConnected(Intent intent) {
        Log.i(TAG, "Power connected");
        if (mBatteryListener != null) {
            mBatteryListener.onPowerConnected();
        }
    }

    private void handlePowerDisconnected() {
        Log.i(TAG, "Power disconnected");
        if (mBatteryListener != null) {
            mBatteryListener.onPowerDisconnected();
        }
    }

    private void handleBootCompleted() {
        Log.i(TAG, "Boot completed");

        // Start AinosService on boot
        Intent serviceIntent = new Intent();
        serviceIntent.setClassName("com.ainos", "com.ainos.AinosService");
        serviceIntent.setAction("com.ainos.action.START_FOREGROUND");
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                getContext().startForegroundService(serviceIntent);
            } else {
                getContext().startService(serviceIntent);
            }
            Log.i(TAG, "AinosService started on boot");
        } catch (Exception e) {
            Log.e(TAG, "Failed to start service on boot", e);
        }

        if (mBootListener != null) {
            mBootListener.onBootCompleted();
        }
    }

    private void handleShutdown() {
        Log.i(TAG, "Device shutting down");
        // Gracefully shutdown native layer
        AinosNative.nativeShutdown();
    }

    private void handleReboot() {
        Log.i(TAG, "Device rebooting");
        AinosNative.nativeShutdown();
    }

    private void handleScreenOn() {
        Log.d(TAG, "Screen on");
    }

    private void handleScreenOff() {
        Log.d(TAG, "Screen off");
    }

    private void handleUserPresent() {
        Log.d(TAG, "User present");
    }

    private void handleTimeChanged() {
        Log.d(TAG, "Time changed");
    }

    private void handleTimezoneChanged() {
        Log.d(TAG, "Timezone changed");
    }

    private void handleLocaleChanged() {
        Log.d(TAG, "Locale changed");
    }

    private void handleIdleModeChanged(Intent intent) {
        boolean isIdle = intent.getBooleanExtra("device_idle", false);
        Log.d(TAG, "Idle mode: " + isIdle);
    }

    private void handlePowerSaveModeChanged(Intent intent) {
        boolean isPowerSave = intent.getBooleanExtra("mode", false);
        Log.i(TAG, "Power save mode: " + isPowerSave);

        if (isPowerSave) {
            AinosNative.nativeSetPowerMode(1); // LOW_POWER
        } else {
            AinosNative.nativeSetPowerMode(0); // NORMAL
        }
    }

    private void handleIdleMaintenanceStart() {
        Log.d(TAG, "Idle maintenance start");
    }

    private void handleIdleMaintenanceEnd() {
        Log.d(TAG, "Idle maintenance end");
    }

    private Context getContext() {
        // This is tricky in a BroadcastReceiver - we store it from onReceive
        // For simplicity, we use a static reference
        return AinosService.getInstance() != null ?
            AinosService.getInstance() : null;
    }

    /**
     * Get the intent filter for all broadcasts this receiver handles.
     */
    public static IntentFilter createIntentFilter() {
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_BATTERY_CHANGED);
        filter.addAction(Intent.ACTION_BATTERY_LOW);
        filter.addAction(Intent.ACTION_BATTERY_OKAY);
        filter.addAction(Intent.ACTION_POWER_CONNECTED);
        filter.addAction(Intent.ACTION_POWER_DISCONNECTED);
        filter.addAction(Intent.ACTION_BOOT_COMPLETED);
        filter.addAction(Intent.ACTION_SHUTDOWN);
        filter.addAction(Intent.ACTION_REBOOT);
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_USER_PRESENT);
        filter.addAction(Intent.ACTION_TIME_TICK);
        filter.addAction(Intent.ACTION_TIME_CHANGED);
        filter.addAction(Intent.ACTION_TIMEZONE_CHANGED);
        filter.addAction(Intent.ACTION_LOCALE_CHANGED);
        filter.addAction("android.os.action.DEVICE_IDLE_MODE_CHANGED");
        filter.addAction("android.os.action.POWER_SAVE_MODE_CHANGED");
        filter.addAction("android.intent.action.ACTION_IDLE_MAINTENANCE_START");
        filter.addAction("android.intent.action.ACTION_IDLE_MAINTENANCE_END");
        return filter;
    }
}