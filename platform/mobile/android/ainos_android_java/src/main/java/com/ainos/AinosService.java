package com.ainos;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import com.ainos.inference.InferenceEngine;
import com.ainos.inference.NNDelegate;
import com.ainos.inference.StreamHandler;
import com.ainos.models.ModelInfo;
import com.ainos.models.InferenceResult;
import com.ainos.utils.BatteryManager;
import com.ainos.utils.ThermalManager;
import com.ainos.utils.Permissions;

import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * AinosService - Android foreground service for Ainos AI platform.
 * Manages background AI inference, thermal monitoring, daemon communication,
 * and keeps the app alive for long-running tasks.
 */
public class AinosService extends Service {

    private static final String TAG = "AinosService";
    private static final String CHANNEL_ID = "ainos_foreground";
    private static final int NOTIFICATION_ID = 1001;
    private static final int HEARTBEAT_INTERVAL_MS = 30000;
    private static final int DAEMON_RECONNECT_DELAY_MS = 5000;
    private static final int MAX_RECONNECT_ATTEMPTS = 10;
    private static final String DAEMON_HOST = "127.0.0.1";
    private static final int DAEMON_PORT = 8732;

    // Singleton instance
    private static AinosService sInstance;

    // Threading
    private HandlerThread mServiceThread;
    private Handler mServiceHandler;
    private final ExecutorService mWorkExecutor = Executors.newFixedThreadPool(4);
    private final ScheduledExecutorService mScheduler = Executors.newScheduledThreadPool(2);

    // State
    private final AtomicBoolean mInitialized = new AtomicBoolean(false);
    private final AtomicBoolean mDaemonConnected = new AtomicBoolean(false);
    private final AtomicInteger mReconnectAttempts = new AtomicInteger(0);
    private PowerManager.WakeLock mWakeLock;
    private boolean mIsBound = false;

    // Components
    private ThermalManager mThermalManager;
    private com.ainos.utils.BatteryManager mBatteryManager;
    private InferenceEngine mInferenceEngine;
    private NNDelegate mNNDelegate;
    private StreamHandler mStreamHandler;
    private DaemonClient mDaemonClient;
    private Permissions mPermissions;

    // Listeners
    private final List<ServiceListener> mListeners = new CopyOnWriteArrayList<>();

    /**
     * Service listener interface for callbacks.
     */
    public interface ServiceListener {
        void onServiceReady();
        void onServiceStopped();
        void onDaemonConnected();
        void onDaemonDisconnected();
        void onThermalWarning(int status);
        void onBatteryLow(int level);
        void onError(String message);
    }

    /**
     * Get the service instance.
     */
    @Nullable
    public static AinosService getInstance() {
        return sInstance;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        sInstance = this;
        Log.i(TAG, "Service created");

        // Initialize service thread
        mServiceThread = new HandlerThread("AinosServiceThread");
        mServiceThread.start();
        mServiceHandler = new Handler(mServiceThread.getLooper());

        // Initialize components
        initializeComponents();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Log.i(TAG, "onStartCommand: " + (intent != null ? intent.getAction() : "null"));

        if (intent != null && intent.getAction() != null) {
            switch (intent.getAction()) {
                case "com.ainos.action.START_FOREGROUND":
                    startForegroundService();
                    break;
                case "com.ainos.action.STOP_FOREGROUND":
                    stopForegroundService();
                    break;
                case "com.ainos.action.CONNECT_DAEMON":
                    connectToDaemon();
                    break;
                case "com.ainos.action.DISCONNECT_DAEMON":
                    disconnectFromDaemon();
                    break;
                case "com.ainos.action.START_INFERENCE":
                    handleInferenceIntent(intent);
                    break;
                case "com.ainos.action.STOP_INFERENCE":
                    stopInference();
                    break;
                case "com.ainos.action.DOWNLOAD_MODEL":
                    handleDownloadIntent(intent);
                    break;
                case "com.ainos.action.UPDATE_NOTIFICATION":
                    updateNotification(
                        intent.getStringExtra("title"),
                        intent.getStringExtra("text"));
                    break;
            }
        }

        // If service is killed, restart with the last intent
        return START_STICKY;
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        mIsBound = true;
        Log.i(TAG, "Service bound");
        return null; // We don't use binding in this implementation
    }

    @Override
    public boolean onUnbind(Intent intent) {
        mIsBound = false;
        Log.i(TAG, "Service unbound");
        return false;
    }

    @Override
    public void onDestroy() {
        Log.i(TAG, "Service destroyed");
        sInstance = null;
        shutdownComponents();
        super.onDestroy();
    }

    /*========================================================================
     * Initialization
     *======================================================================*/

    private void initializeComponents() {
        mServiceHandler.post(() -> {
            try {
                Log.i(TAG, "Initializing components...");

                // Initialize C native layer
                int result = AinosNative.nativeInit("Ainos", "1.0.0");
                if (result != 0) {
                    Log.e(TAG, "Native init failed: " + result);
                    notifyError("Native initialization failed: " + result);
                    return;
                }

                // Initialize managers
                mThermalManager = new ThermalManager(this);
                mBatteryManager = new com.ainos.utils.BatteryManager(this);
                mPermissions = new Permissions(this);
                mNNDelegate = new NNDelegate(this);
                mInferenceEngine = new InferenceEngine(this, mNNDelegate, mThermalManager);
                mStreamHandler = new StreamHandler(mInferenceEngine);

                // Start thermal monitoring
                mThermalManager.startMonitoring(mThermalCallback);

                // Start battery monitoring
                mBatteryManager.startMonitoring(mBatteryCallback);

                mInitialized.set(true);
                Log.i(TAG, "Components initialized successfully");

                // Notify listeners
                for (ServiceListener listener : mListeners) {
                    listener.onServiceReady();
                }

            } catch (Exception e) {
                Log.e(TAG, "Failed to initialize components", e);
                notifyError("Init failed: " + e.getMessage());
            }
        });
    }

    private void shutdownComponents() {
        Log.i(TAG, "Shutting down components...");

        mScheduler.shutdownNow();
        mWorkExecutor.shutdownNow();

        if (mStreamHandler != null) {
            mStreamHandler.shutdown();
        }
        if (mInferenceEngine != null) {
            mInferenceEngine.shutdown();
        }
        if (mThermalManager != null) {
            mThermalManager.stopMonitoring();
        }
        if (mBatteryManager != null) {
            mBatteryManager.stopMonitoring();
        }
        if (mDaemonClient != null) {
            mDaemonClient.disconnect();
        }
        if (mWakeLock != null && mWakeLock.isHeld()) {
            mWakeLock.release();
        }

        AinosNative.nativeShutdown();

        if (mServiceThread != null) {
            mServiceThread.quitSafely();
        }

        Log.i(TAG, "Components shut down");
    }

    /*========================================================================
     * Foreground Service
     *======================================================================*/

    private void startForegroundService() {
        createNotificationChannel();

        Notification notification = buildNotification(
            "Ainos AI Platform",
            "Running in background",
            NotificationCompat.PRIORITY_LOW);

        startForeground(NOTIFICATION_ID, notification);

        // Acquire wake lock for long-running tasks
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (pm != null) {
            mWakeLock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "AinosService:WakeLock");
            mWakeLock.acquire(10 * 60 * 1000L); // 10 minutes max
        }

        // Start heartbeat to daemon
        mScheduler.scheduleAtFixedRate(
            this::sendHeartbeat,
            HEARTBEAT_INTERVAL_MS,
            HEARTBEAT_INTERVAL_MS,
            TimeUnit.MILLISECONDS);

        Log.i(TAG, "Foreground service started");
    }

    private void stopForegroundService() {
        if (mWakeLock != null && mWakeLock.isHeld()) {
            mWakeLock.release();
        }
        stopForeground(true);
        stopSelf();
        Log.i(TAG, "Foreground service stopped");
    }

    private void updateNotification(String title, String text) {
        if (title == null) title = "Ainos AI Platform";
        if (text == null) text = "Running in background";

        Notification notification = buildNotification(title, text, NotificationCompat.PRIORITY_LOW);
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) {
            nm.notify(NOTIFICATION_ID, notification);
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Ainos Service",
                NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Ainos AI platform background service");
            channel.setShowBadge(false);

            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
    }

    private Notification buildNotification(String title, String text, int priority) {
        // Create a pending intent for the main activity
        PendingIntent pendingIntent = PendingIntent.getActivity(
            this, 0,
            new Intent(this, getMainActivityClass()),
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        // Create stop action
        Intent stopIntent = new Intent(this, AinosService.class);
        stopIntent.setAction("com.ainos.action.STOP_FOREGROUND");
        PendingIntent stopPendingIntent = PendingIntent.getService(
            this, 1, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setPriority(priority)
            .setContentIntent(pendingIntent)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopPendingIntent)
            .setOngoing(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build();
    }

    private Class<?> getMainActivityClass() {
        try {
            return Class.forName("com.ainos.MainActivity");
        } catch (ClassNotFoundException e) {
            Log.w(TAG, "MainActivity not found");
            return AinosService.class;
        }
    }

    /*========================================================================
     * Daemon Communication
     *======================================================================*/

    private void connectToDaemon() {
        mWorkExecutor.execute(() -> {
            try {
                Log.i(TAG, "Connecting to daemon at " + DAEMON_HOST + ":" + DAEMON_PORT);

                int result = AinosNative.nativeConnectDaemon(DAEMON_HOST, DAEMON_PORT, 10000);
                if (result == 0) {
                    mDaemonConnected.set(true);
                    mReconnectAttempts.set(0);

                    mDaemonClient = new DaemonClient(DAEMON_HOST, DAEMON_PORT);
                    mDaemonClient.start();

                    Log.i(TAG, "Connected to daemon");

                    for (ServiceListener listener : mListeners) {
                        listener.onDaemonConnected();
                    }
                } else {
                    Log.e(TAG, "Failed to connect to daemon: " + result);
                    scheduleReconnect();
                }
            } catch (Exception e) {
                Log.e(TAG, "Error connecting to daemon", e);
                scheduleReconnect();
            }
        });
    }

    private void disconnectFromDaemon() {
        if (mDaemonClient != null) {
            mDaemonClient.disconnect();
            mDaemonClient = null;
        }
        mDaemonConnected.set(false);
        AinosNative.nativeConnectDaemon("", 0, 0); // Force disconnect

        for (ServiceListener listener : mListeners) {
            listener.onDaemonDisconnected();
        }
    }

    private void scheduleReconnect() {
        if (mReconnectAttempts.get() >= MAX_RECONNECT_ATTEMPTS) {
            Log.e(TAG, "Max reconnect attempts reached");
            notifyError("Failed to connect to daemon after " + MAX_RECONNECT_ATTEMPTS + " attempts");
            return;
        }

        int delay = DAEMON_RECONNECT_DELAY_MS * (1 << mReconnectAttempts.get());
        mReconnectAttempts.incrementAndGet();

        Log.i(TAG, "Scheduling reconnect attempt " + mReconnectAttempts.get() +
              " in " + delay + "ms");

        mServiceHandler.postDelayed(this::connectToDaemon, delay);
    }

    private void sendHeartbeat() {
        if (mDaemonConnected.get() && mDaemonClient != null) {
            mDaemonClient.sendHeartbeat();
        }
    }

    /**
     * Internal daemon communication client using TCP sockets.
     */
    private class DaemonClient extends Thread {
        private final String mHost;
        private final int mPort;
        private final AtomicBoolean mRunning = new AtomicBoolean(false);
        private Socket mSocket;
        private int mSequence = 0;

        DaemonClient(String host, int port) {
            super("DaemonClient");
            mHost = host;
            mPort = port;
        }

        @Override
        public void run() {
            mRunning.set(true);

            while (mRunning.get()) {
                try {
                    // Connect socket
                    mSocket = new Socket();
                    mSocket.connect(new InetSocketAddress(mHost, mPort), 5000);
                    mSocket.setSoTimeout(10000);

                    Log.i(TAG, "Daemon socket connected");

                    // Register with daemon
                    sendRegister();

                    // Main message loop
                    while (mRunning.get() && mSocket.isConnected()) {
                        // Read message header (8 bytes: command + sequence + payload_size)
                        byte[] header = new byte[12];
                        int bytesRead = readFully(mSocket.getInputStream(), header, header.length);
                        if (bytesRead < header.length) {
                            Log.w(TAG, "Daemon connection closed");
                            break;
                        }

                        ByteBuffer buffer = ByteBuffer.wrap(header).order(ByteOrder.BIG_ENDIAN);
                        int command = buffer.getInt();
                        int sequence = buffer.getInt();
                        int payloadSize = buffer.getInt();

                        // Read payload
                        byte[] payload = new byte[payloadSize];
                        if (payloadSize > 0) {
                            readFully(mSocket.getInputStream(), payload, payloadSize);
                        }

                        // Handle message
                        handleDaemonMessage(command, sequence, payload);
                    }

                } catch (IOException e) {
                    if (mRunning.get()) {
                        Log.w(TAG, "Daemon connection error: " + e.getMessage());
                    }
                } catch (Exception e) {
                    Log.e(TAG, "Daemon client error", e);
                } finally {
                    closeSocket();
                }

                // Reconnect if still running
                if (mRunning.get()) {
                    try {
                        Thread.sleep(DAEMON_RECONNECT_DELAY_MS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                }
            }
        }

        void disconnect() {
            mRunning.set(false);
            closeSocket();
            interrupt();
        }

        void sendHeartbeat() {
            sendMessage(0x0001, new byte[0]); // HEARTBEAT
        }

        void sendMessage(int command, byte[] payload) {
            if (mSocket == null || !mSocket.isConnected()) {
                Log.w(TAG, "Cannot send message, not connected");
                return;
            }

            try {
                int sequence = mSequence++;
                ByteBuffer header = ByteBuffer.allocate(12).order(ByteOrder.BIG_ENDIAN);
                header.putInt(command);
                header.putInt(sequence);
                header.putInt(payload.length);

                synchronized (mSocket) {
                    mSocket.getOutputStream().write(header.array());
                    if (payload.length > 0) {
                        mSocket.getOutputStream().write(payload);
                    }
                    mSocket.getOutputStream().flush();
                }
            } catch (IOException e) {
                Log.e(TAG, "Failed to send message", e);
            }
        }

        private void sendRegister() {
            try {
                // Build registration payload
                String deviceInfo = AinosNative.nativeGetDeviceInfo();
                byte[] payload = deviceInfo.getBytes("UTF-8");
                sendMessage(0x0003, payload); // REGISTER_CLIENT
            } catch (Exception e) {
                Log.e(TAG, "Failed to send register", e);
            }
        }

        private void handleDaemonMessage(int command, int sequence, byte[] payload) {
            Log.d(TAG, "Daemon message: cmd=0x" + Integer.toHexString(command) +
                  " seq=" + sequence + " size=" + payload.length);

            switch (command) {
                case 0x0001: // HEARTBEAT response
                    break;
                case 0x0002: // GET_STATUS response
                    handleStatusResponse(payload);
                    break;
                case 0x0010: // MODEL_LIST response
                    handleModelListResponse(payload);
                    break;
                case 0x0020: // INFERENCE request
                    handleDaemonInferenceRequest(payload);
                    break;
                case 0x0040: // PUSH_NOTIFICATION
                    handlePushNotification(payload);
                    break;
                case 0x0030: // SYSTEM_UPDATE
                    handleSystemUpdate(payload);
                    break;
                default:
                    Log.d(TAG, "Unknown command: 0x" + Integer.toHexString(command));
            }
        }

        private void handleStatusResponse(byte[] payload) {
            // Parse and update status
            Log.i(TAG, "Daemon status response: " + payload.length + " bytes");
        }

        private void handleModelListResponse(byte[] payload) {
            Log.i(TAG, "Model list received: " + payload.length + " bytes");
        }

        private void handleDaemonInferenceRequest(byte[] payload) {
            Log.i(TAG, "Inference request from daemon");
        }

        private void handlePushNotification(byte[] payload) {
            try {
                String message = new String(payload, "UTF-8");
                Log.i(TAG, "Push notification: " + message);

                ainos_notification_t notif = new ainos_notification_t();
                notif.title = "Ainos";
                notif.body = message;
                showNotification(notif);
            } catch (Exception e) {
                Log.e(TAG, "Failed to handle push notification", e);
            }
        }

        private void handleSystemUpdate(byte[] payload) {
            Log.i(TAG, "System update available");
        }

        private void closeSocket() {
            try {
                if (mSocket != null) {
                    mSocket.close();
                }
            } catch (IOException e) {
                // Ignore
            }
            mSocket = null;
        }

        private int readFully(java.io.InputStream is, byte[] buffer, int length) throws IOException {
            int totalRead = 0;
            while (totalRead < length) {
                int read = is.read(buffer, totalRead, length - totalRead);
                if (read < 0) {
                    return totalRead;
                }
                totalRead += read;
            }
            return totalRead;
        }
    }

    /*========================================================================
     * Callbacks
     *======================================================================*/

    private final ThermalManager.ThermalCallback mThermalCallback =
        new ThermalManager.ThermalCallback() {
            @Override
            public void onThermalStatusChanged(int oldStatus, int newStatus) {
                Log.i(TAG, "Thermal status: " + oldStatus + " -> " + newStatus);
                for (ServiceListener listener : mListeners) {
                    listener.onThermalWarning(newStatus);
                }

                // Update notification
                if (newStatus >= 3) { // Critical or higher
                    updateNotification(
                        "Ainos - Thermal Warning",
                        "Device is overheating. Performance may be limited.");
                }
            }

            @Override
            public void onTemperatureReading(float cpuTemp, float batteryTemp) {
                // Log periodically
            }
        };

    private final com.ainos.utils.BatteryManager.BatteryCallback mBatteryCallback =
        new com.ainos.utils.BatteryManager.BatteryCallback() {
            @Override
            public void onBatteryLevelChanged(int level) {
                if (level <= 15) {
                    Log.w(TAG, "Battery low: " + level + "%");
                    for (ServiceListener listener : mListeners) {
                        listener.onBatteryLow(level);
                    }
                }
            }

            @Override
            public void onChargingStatusChanged(boolean isCharging) {
                Log.i(TAG, "Charging: " + isCharging);
            }
        };

    /*========================================================================
     * Public API
     *======================================================================*/

    /**
     * Check if the service is initialized.
     */
    public boolean isInitialized() {
        return mInitialized.get();
    }

    /**
     * Get the inference engine.
     */
    public InferenceEngine getInferenceEngine() {
        return mInferenceEngine;
    }

    /**
     * Get the stream handler.
     */
    public StreamHandler getStreamHandler() {
        return mStreamHandler;
    }

    /**
     * Get the thermal manager.
     */
    public ThermalManager getThermalManager() {
        return mThermalManager;
    }

    /**
     * Get the battery manager.
     */
    public com.ainos.utils.BatteryManager getBatteryManager() {
        return mBatteryManager;
    }

    /**
     * Get the permissions helper.
     */
    public Permissions getPermissions() {
        return mPermissions;
    }

    /**
     * Get the NN delegate.
     */
    public NNDelegate getNNDelegate() {
        return mNNDelegate;
    }

    /**
     * Check if daemon is connected.
     */
    public boolean isDaemonConnected() {
        return mDaemonConnected.get();
    }

    /**
     * Register a service listener.
     */
    public void addListener(ServiceListener listener) {
        if (listener != null && !mListeners.contains(listener)) {
            mListeners.add(listener);
        }
    }

    /**
     * Unregister a service listener.
     */
    public void removeListener(ServiceListener listener) {
        mListeners.remove(listener);
    }

    /**
     * Start model download.
     */
    public void downloadModel(String modelId) {
        mWorkExecutor.execute(() -> {
            int result = AinosNative.nativeModelDownload(modelId);
            if (result != 0) {
                notifyError("Model download failed: " + result);
            }
        });
    }

    /**
     * Load a model for inference.
     */
    public void loadModel(String modelId) {
        mWorkExecutor.execute(() -> {
            int result = AinosNative.nativeModelLoad(modelId);
            if (result == 0) {
                Log.i(TAG, "Model loaded: " + modelId);
            } else {
                notifyError("Model load failed: " + result);
            }
        });
    }

    /**
     * Show a notification.
     */
    public void showNotification(String title, String body) {
        ainos_notification_t notif = new ainos_notification_t();
        notif.title = title;
        notif.body = body;
        showNotification(notif);
    }

    /**
     * Send a command to the daemon.
     */
    public void sendDaemonCommand(int command, byte[] request, DaemonResponseCallback callback) {
        mWorkExecutor.execute(() -> {
            try {
                byte[] response = new byte[4096];
                int result = AinosNative.nativeSendDaemonCommand(command, request, response);
                if (callback != null) {
                    callback.onResponse(result, response);
                }
            } catch (Exception e) {
                Log.e(TAG, "Daemon command failed", e);
                if (callback != null) {
                    callback.onResponse(-1, null);
                }
            }
        });
    }

    /**
     * Callback for daemon responses.
     */
    public interface DaemonResponseCallback {
        void onResponse(int result, byte[] data);
    }

    /*========================================================================
     * Internal Helpers
     *======================================================================*/

    private void handleInferenceIntent(Intent intent) {
        String modelId = intent.getStringExtra("model_id");
        byte[] inputData = intent.getByteArrayExtra("input_data");

        if (modelId == null || inputData == null) {
            Log.e(TAG, "Invalid inference intent");
            return;
        }

        mWorkExecutor.execute(() -> {
            try {
                ModelInfo model = new ModelInfo(modelId, modelId, 0);
                InferenceResult result = mInferenceEngine.runInference(model, inputData);
                Log.i(TAG, "Inference completed: " + result.status);
            } catch (Exception e) {
                Log.e(TAG, "Inference failed", e);
            }
        });
    }

    private void handleDownloadIntent(Intent intent) {
        String modelId = intent.getStringExtra("model_id");
        if (modelId != null) {
            downloadModel(modelId);
        }
    }

    private void stopInference() {
        if (mInferenceEngine != null) {
            mInferenceEngine.cancelAll();
        }
    }

    private void showNotification(ainos_notification_t notif) {
        int priority = NotificationCompat.PRIORITY_DEFAULT;
        switch (notif.priority) {
            case 0: priority = NotificationCompat.PRIORITY_MIN; break;
            case 1: priority = NotificationCompat.PRIORITY_LOW; break;
            case 2: priority = NotificationCompat.PRIORITY_DEFAULT; break;
            case 3: priority = NotificationCompat.PRIORITY_HIGH; break;
            case 4: priority = NotificationCompat.PRIORITY_MAX; break;
        }

        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(notif.title)
            .setContentText(notif.body)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setPriority(priority)
            .setAutoCancel(notif.autoCancel)
            .build();

        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.notify((int) System.currentTimeMillis(), notification);
        }
    }

    private void notifyError(String message) {
        Log.e(TAG, message);
        for (ServiceListener listener : mListeners) {
            listener.onError(message);
        }
    }

    /**
     * Internal notification data class.
     */
    private static class ainos_notification_t {
        String title = "";
        String body = "";
        int priority = 2;
        boolean autoCancel = true;
        boolean vibrate = true;
    }
}