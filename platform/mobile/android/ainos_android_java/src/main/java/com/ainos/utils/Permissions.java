package com.ainos.utils;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.ainos.AinosNative;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Permissions - Manages Android runtime permissions for the Ainos platform.
 * Provides a unified interface for requesting and checking permissions.
 */
public class Permissions {

    private static final String TAG = "Permissions";

    // Permission codes matching C API
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

    // State constants
    public static final int STATE_NOT_DETERMINED = 0;
    public static final int STATE_GRANTED = 1;
    public static final int STATE_DENIED = 2;
    public static final int STATE_RESTRICTED = 3;
    public static final int STATE_DENIED_FOREVER = 4;

    private final Context mContext;
    private final Map<Integer, PermissionCallback> mPendingRequests;
    private int mRequestCodeCounter = 1000;

    /**
     * Callback for permission request results.
     */
    public interface PermissionCallback {
        void onPermissionResult(int permission, int state);
    }

    /**
     * Create the permissions manager.
     */
    public Permissions(Context context) {
        mContext = context;
        mPendingRequests = new ConcurrentHashMap<>();
    }

    /**
     * Check the state of a permission.
     *
     * @param permission Permission code from AinosNative.Permission
     * @return Permission state
     */
    public int checkPermission(int permission) {
        String androidPermission = mapToAndroidPermission(permission);
        if (androidPermission == null) {
            // Permissions that don't need runtime check
            return STATE_GRANTED;
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return STATE_GRANTED;
        }

        if (ContextCompat.checkSelfPermission(mContext, androidPermission)
                == PackageManager.PERMISSION_GRANTED) {
            return STATE_GRANTED;
        }

        // Check if we should show rationale (denied before)
        Activity activity = getActivity();
        if (activity != null) {
            if (ActivityCompat.shouldShowRequestPermissionRationale(
                    activity, androidPermission)) {
                return STATE_DENIED;
            } else {
                // Check if permanently denied
                if (isPermissionPermanentlyDenied(activity, androidPermission)) {
                    return STATE_DENIED_FOREVER;
                }
                return STATE_NOT_DETERMINED;
            }
        }

        return STATE_NOT_DETERMINED;
    }

    /**
     * Request a permission.
     *
     * @param permission Permission code
     * @param callback   Callback for result
     */
    public void requestPermission(int permission, PermissionCallback callback) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            if (callback != null) {
                callback.onPermissionResult(permission, STATE_GRANTED);
            }
            return;
        }

        String androidPermission = mapToAndroidPermission(permission);
        if (androidPermission == null) {
            if (callback != null) {
                callback.onPermissionResult(permission, STATE_GRANTED);
            }
            return;
        }

        // Check if already granted
        if (checkPermission(permission) == STATE_GRANTED) {
            if (callback != null) {
                callback.onPermissionResult(permission, STATE_GRANTED);
            }
            return;
        }

        Activity activity = getActivity();
        if (activity == null) {
            Log.w(TAG, "No activity to request permission");
            if (callback != null) {
                callback.onPermissionResult(permission, STATE_DENIED);
            }
            return;
        }

        int requestCode = mRequestCodeCounter++;
        mPendingRequests.put(requestCode, callback);

        ActivityCompat.requestPermissions(
            activity,
            new String[]{androidPermission},
            requestCode);

        Log.i(TAG, "Requesting permission: " + getPermissionName(permission) +
              " (code=" + requestCode + ")");
    }

    /**
     * Request multiple permissions at once.
     *
     * @param permissions Array of permission codes
     * @param callback    Callback for each result
     */
    public void requestPermissions(int[] permissions, PermissionCallback callback) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            for (int perm : permissions) {
                if (callback != null) {
                    callback.onPermissionResult(perm, STATE_GRANTED);
                }
            }
            return;
        }

        Activity activity = getActivity();
        if (activity == null) {
            Log.w(TAG, "No activity to request permissions");
            for (int perm : permissions) {
                if (callback != null) {
                    callback.onPermissionResult(perm, STATE_DENIED);
                }
            }
            return;
        }

        List<String> androidPermissions = new ArrayList<>();
        for (int perm : permissions) {
            String androidPerm = mapToAndroidPermission(perm);
            if (androidPerm != null &&
                checkPermission(perm) != STATE_GRANTED) {
                androidPermissions.add(androidPerm);
            }
        }

        if (androidPermissions.isEmpty()) {
            // All already granted
            for (int perm : permissions) {
                if (callback != null) {
                    callback.onPermissionResult(perm, STATE_GRANTED);
                }
            }
            return;
        }

        int requestCode = mRequestCodeCounter++;
        mPendingRequests.put(requestCode, callback);

        ActivityCompat.requestPermissions(
            activity,
            androidPermissions.toArray(new String[0]),
            requestCode);

        Log.i(TAG, "Requesting " + androidPermissions.size() + " permissions");
    }

    /**
     * Handle the result of a permission request.
     * Should be called from Activity.onRequestPermissionsResult().
     */
    public void handleRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults) {

        PermissionCallback callback = mPendingRequests.remove(requestCode);
        if (callback == null) {
            Log.w(TAG, "No callback for request code: " + requestCode);
            return;
        }

        for (int i = 0; i < permissions.length; i++) {
            int permissionCode = mapFromAndroidPermission(permissions[i]);
            int state;

            if (grantResults[i] == PackageManager.PERMISSION_GRANTED) {
                state = STATE_GRANTED;
            } else {
                // Check if permanently denied
                Activity activity = getActivity();
                if (activity != null && !ActivityCompat.shouldShowRequestPermissionRationale(
                        activity, permissions[i])) {
                    state = STATE_DENIED_FOREVER;
                } else {
                    state = STATE_DENIED;
                }
            }

            Log.i(TAG, "Permission result: " + getPermissionName(permissionCode) +
                  " -> " + getStateString(state));

            callback.onPermissionResult(permissionCode, state);
        }
    }

    /**
     * Check if we should show a rationale for a permission.
     */
    public boolean shouldShowRationale(int permission) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return false;
        }

        String androidPermission = mapToAndroidPermission(permission);
        if (androidPermission == null) return false;

        Activity activity = getActivity();
        if (activity == null) return false;

        return ActivityCompat.shouldShowRequestPermissionRationale(
            activity, androidPermission);
    }

    /**
     * Open the app's permission settings page.
     */
    public void openSettings() {
        Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        Uri uri = Uri.fromParts("package", mContext.getPackageName(), null);
        intent.setData(uri);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        mContext.startActivity(intent);
        Log.i(TAG, "Opening app settings");
    }

    /**
     * Check if all required permissions are granted.
     */
    public boolean hasRequiredPermissions() {
        int[] required = {
            NETWORK_STATE, WAKE_LOCK, FOREGROUND_SERVICE,
            VIBRATE, POST_NOTIFICATIONS
        };
        for (int perm : required) {
            if (checkPermission(perm) != STATE_GRANTED) {
                return false;
            }
        }
        return true;
    }

    /**
     * Get the display name for a permission.
     */
    public static String getPermissionName(int permission) {
        return AinosNative.Permission.getName(permission);
    }

    /**
     * Get the state as a string.
     */
    public static String getStateString(int state) {
        switch (state) {
            case STATE_NOT_DETERMINED: return "Not Determined";
            case STATE_GRANTED: return "Granted";
            case STATE_DENIED: return "Denied";
            case STATE_RESTRICTED: return "Restricted";
            case STATE_DENIED_FOREVER: return "Denied Forever";
            default: return "Unknown";
        }
    }

    /**
     * Map Ainos permission code to Android permission string.
     */
    private String mapToAndroidPermission(int permission) {
        switch (permission) {
            case CAMERA:
                return Manifest.permission.CAMERA;
            case MICROPHONE:
                return Manifest.permission.RECORD_AUDIO;
            case STORAGE:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    return Manifest.permission.READ_MEDIA_IMAGES;
                }
                return Manifest.permission.READ_EXTERNAL_STORAGE;
            case NOTIFICATIONS:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    return Manifest.permission.POST_NOTIFICATIONS;
                }
                return null; // Not needed on older versions
            case BACKGROUND_SERVICE:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    return Manifest.permission.FOREGROUND_SERVICE;
                }
                return null;
            case NETWORK_STATE:
                return Manifest.permission.ACCESS_NETWORK_STATE;
            case BLUETOOTH:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    return Manifest.permission.BLUETOOTH_CONNECT;
                }
                return Manifest.permission.BLUETOOTH;
            case LOCATION:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    return Manifest.permission.ACCESS_FINE_LOCATION;
                }
                return Manifest.permission.ACCESS_FINE_LOCATION;
            case VIBRATE:
                return Manifest.permission.VIBRATE;
            case WAKE_LOCK:
                return Manifest.permission.WAKE_LOCK;
            case FOREGROUND_SERVICE:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    return Manifest.permission.FOREGROUND_SERVICE;
                }
                return null;
            case SCHEDULE_EXACT_ALARM:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    return Manifest.permission.SCHEDULE_EXACT_ALARM;
                }
                return null;
            case POST_NOTIFICATIONS:
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    return Manifest.permission.POST_NOTIFICATIONS;
                }
                return null;
            default:
                return null;
        }
    }

    /**
     * Map Android permission string back to Ainos permission code.
     */
    private int mapFromAndroidPermission(String androidPermission) {
        if (androidPermission == null) return -1;

        switch (androidPermission) {
            case Manifest.permission.CAMERA: return CAMERA;
            case Manifest.permission.RECORD_AUDIO: return MICROPHONE;
            case Manifest.permission.READ_EXTERNAL_STORAGE:
            case Manifest.permission.READ_MEDIA_IMAGES: return STORAGE;
            case Manifest.permission.POST_NOTIFICATIONS: return POST_NOTIFICATIONS;
            case Manifest.permission.FOREGROUND_SERVICE: return BACKGROUND_SERVICE;
            case Manifest.permission.ACCESS_NETWORK_STATE: return NETWORK_STATE;
            case Manifest.permission.BLUETOOTH:
            case Manifest.permission.BLUETOOTH_CONNECT: return BLUETOOTH;
            case Manifest.permission.ACCESS_FINE_LOCATION: return LOCATION;
            case Manifest.permission.VIBRATE: return VIBRATE;
            case Manifest.permission.WAKE_LOCK: return WAKE_LOCK;
            case Manifest.permission.SCHEDULE_EXACT_ALARM: return SCHEDULE_EXACT_ALARM;
            default: return -1;
        }
    }

    /**
     * Check if a permission is permanently denied.
     */
    private boolean isPermissionPermanentlyDenied(Activity activity, String permission) {
        return !ActivityCompat.shouldShowRequestPermissionRationale(activity, permission);
    }

    /**
     * Get the current activity from the context.
     */
    private Activity getActivity() {
        if (mContext instanceof Activity) {
            return (Activity) mContext;
        }
        // Try to get the activity from the application context
        // This is a simplified approach - in production use a proper reference
        return null;
    }
}