package com.ainos.inference;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import com.ainos.AinosNative;
import com.ainos.models.ModelInfo;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * NNDelegate - Neural Network hardware acceleration delegate for Android.
 * Manages NNAPI, GPU, and XNNPACK delegates for accelerated inference.
 */
public class NNDelegate {

    private static final String TAG = "NNDelegate";

    // Backend types matching C API
    public static final int BACKEND_AUTO = 0;
    public static final int BACKEND_CPU = 1;
    public static final int BACKEND_GPU = 2;
    public static final int BACKEND_NNAPI = 3;
    public static final int BACKEND_COREML = 4;
    public static final int BACKEND_ANE = 5;
    public static final int BACKEND_DELEGATE = 6;

    private final Context mContext;
    private final List<Integer> mAvailableBackends;
    private int mActiveBackend;
    private boolean mNNApiAvailable;
    private boolean mGpuDelegateAvailable;
    private boolean mXnnpackAvailable;
    private String mNNApiDeviceName;
    private int mNNApiDeviceType;

    /**
     * Information about available backends.
     */
    public static class BackendInfo {
        public final int type;
        public final String name;
        public final boolean available;
        public final String description;

        public BackendInfo(int type, String name, boolean available, String description) {
            this.type = type;
            this.name = name;
            this.available = available;
            this.description = description;
        }
    }

    /**
     * Create the NN delegate.
     */
    public NNDelegate(Context context) {
        mContext = context;
        mAvailableBackends = new ArrayList<>();
        mActiveBackend = BACKEND_AUTO;

        detectBackends();
    }

    /**
     * Detect available hardware backends.
     */
    private void detectBackends() {
        mAvailableBackends.clear();

        // CPU is always available
        mAvailableBackends.add(BACKEND_CPU);

        // Check NNAPI availability
        mNNApiAvailable = checkNNAPI();
        if (mNNApiAvailable) {
            mAvailableBackends.add(BACKEND_NNAPI);
            Log.i(TAG, "NNAPI available: " + mNNApiDeviceName);
        }

        // Check GPU delegate
        mGpuDelegateAvailable = checkGPUDelegate();
        if (mGpuDelegateAvailable) {
            mAvailableBackends.add(BACKEND_GPU);
            Log.i(TAG, "GPU delegate available");
        }

        // Check XNNPACK
        mXnnpackAvailable = checkXNNPACK();
        if (mXnnpackAvailable) {
            Log.i(TAG, "XNNPACK available");
        }

        // Auto backend is always available
        mAvailableBackends.add(BACKEND_AUTO);

        Log.i(TAG, "Available backends: " + mAvailableBackends.size());
    }

    /**
     * Check if NNAPI is available on this device.
     */
    private boolean checkNNAPI() {
        // NNAPI requires API level 27+
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O_MR1) {
            return false;
        }

        // Check for NNAPI feature flag
        if (mContext.getPackageManager() != null) {
            boolean hasNNAPI = mContext.getPackageManager()
                .hasSystemFeature("android.hardware.ml.neuralnetworks");
            if (!hasNNAPI) {
                // NNAPI might still be available even without the feature flag
                // Try loading the native library
                try {
                    System.loadLibrary("neuralnetworks");
                    return true;
                } catch (UnsatisfiedLinkError e) {
                    return false;
                }
            }
        }

        // Try to determine the device name
        int apiLevel = Build.VERSION.SDK_INT;
        if (apiLevel >= 29) {
            mNNApiDeviceName = "NNAPI (Android " + apiLevel + ")";
            // Try to get actual device name via native
            try {
                String deviceInfo = AinosNative.nativeGetDeviceInfo();
                Log.d(TAG, "Device info for NNAPI: " + deviceInfo);
            } catch (Exception e) {
                // Ignore
            }
        } else {
            mNNApiDeviceName = "NNAPI";
        }

        return true;
    }

    /**
     * Check if GPU delegate is available.
     */
    private boolean checkGPUDelegate() {
        // GPU delegate requires OpenGL ES 3.1+
        // Check via native
        try {
            System.loadLibrary("gpu_delegate");
            return true;
        } catch (UnsatisfiedLinkError e) {
            try {
                System.loadLibrary("tensorflowlite_gpu_jni");
                return true;
            } catch (UnsatisfiedLinkError e2) {
                return false;
            }
        }
    }

    /**
     * Check if XNNPACK is available.
     */
    private boolean checkXNNPACK() {
        try {
            System.loadLibrary("XNNPACK");
            return true;
        } catch (UnsatisfiedLinkError e) {
            try {
                System.loadLibrary("xnnpack_delegate");
                return true;
            } catch (UnsatisfiedLinkError e2) {
                return false;
            }
        }
    }

    /**
     * Initialize the delegate for a specific model.
     *
     * @param modelInfo Model to initialize for
     * @return true if initialization succeeded
     */
    public boolean initializeForModel(ModelInfo modelInfo) {
        Log.i(TAG, "Initializing delegate for model: " + modelInfo.modelId +
              " format=" + modelInfo.getFormatString());

        // Select the best backend based on configuration
        int backend = selectBackend(modelInfo);
        mActiveBackend = backend;

        Log.i(TAG, "Selected backend: " + getBackendName(backend));

        // Initialize the selected backend
        switch (backend) {
            case BACKEND_NNAPI:
                return initializeNNAPI(modelInfo);
            case BACKEND_GPU:
                return initializeGPU(modelInfo);
            case BACKEND_CPU:
                return initializeCPU(modelInfo);
            default:
                return initializeCPU(modelInfo);
        }
    }

    /**
     * Select the best backend for a given model.
     */
    private int selectBackend(ModelInfo modelInfo) {
        // Prefer NNAPI for quantized models on newer devices
        if (mNNApiAvailable && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (modelInfo.precision == ModelInfo.PRECISION_INT8 ||
                modelInfo.precision == ModelInfo.PRECISION_INT4) {
                return BACKEND_NNAPI;
            }
        }

        // Prefer GPU for FP16 models
        if (mGpuDelegateAvailable && modelInfo.precision == ModelInfo.PRECISION_FP16) {
            return BACKEND_GPU;
        }

        // Use CPU for everything else
        return BACKEND_CPU;
    }

    /**
     * Initialize NNAPI delegate.
     */
    private boolean initializeNNAPI(ModelInfo modelInfo) {
        Log.i(TAG, "Initializing NNAPI for " + modelInfo.modelId);

        // NNAPI initialization is done in native code
        // We just verify it's available
        return mNNApiAvailable;
    }

    /**
     * Initialize GPU delegate.
     */
    private boolean initializeGPU(ModelInfo modelInfo) {
        Log.i(TAG, "Initializing GPU delegate for " + modelInfo.modelId);

        if (!mGpuDelegateAvailable) {
            Log.w(TAG, "GPU delegate not available");
            return false;
        }

        // GPU delegate initialization
        // In production, this would create TFLite GPU delegate options
        try {
            // Check for required OpenGL version
            String glInfo = null;
            try {
                Class<?> glHelper = Class.forName("android.opengl.GLES31");
                glInfo = "GLES 3.1+ available";
            } catch (ClassNotFoundException e) {
                Log.w(TAG, "GLES 3.1 not available, GPU may not work");
            }

            Log.i(TAG, "GPU delegate ready: " + glInfo);
            return true;
        } catch (Exception e) {
            Log.e(TAG, "GPU delegate init failed", e);
            return false;
        }
    }

    /**
     * Initialize CPU delegate.
     */
    private boolean initializeCPU(ModelInfo modelInfo) {
        Log.i(TAG, "Initializing CPU for " + modelInfo.modelId);

        // CPU is always available
        // Configure thread count based on device
        int numThreads = Math.min(Runtime.getRuntime().availableProcessors(), 4);

        if (mXnnpackAvailable) {
            Log.i(TAG, "Using XNNPACK with " + numThreads + " threads");
        } else {
            Log.i(TAG, "Using CPU with " + numThreads + " threads");
        }

        return true;
    }

    /**
     * Get the active backend type.
     */
    public int getActiveBackend() {
        return mActiveBackend;
    }

    /**
     * Get the name of the active backend.
     */
    public String getActiveBackendName() {
        return getBackendName(mActiveBackend);
    }

    /**
     * Get the list of available backends.
     */
    public List<Integer> getAvailableBackends() {
        return new ArrayList<>(mAvailableBackends);
    }

    /**
     * Get detailed info about available backends.
     */
    public List<BackendInfo> getBackendInfoList() {
        List<BackendInfo> infoList = new ArrayList<>();
        infoList.add(new BackendInfo(BACKEND_CPU, "CPU", true,
            "CPU inference with XNNPACK optimization"));
        infoList.add(new BackendInfo(BACKEND_GPU, "GPU", mGpuDelegateAvailable,
            "GPU acceleration via OpenGL ES 3.1+"));
        infoList.add(new BackendInfo(BACKEND_NNAPI, "NNAPI", mNNApiAvailable,
            "Android Neural Networks API (API 27+)"));
        infoList.add(new BackendInfo(BACKEND_AUTO, "Auto", true,
            "Automatic backend selection"));
        return infoList;
    }

    /**
     * Get the name for a backend type.
     */
    public static String getBackendName(int backend) {
        switch (backend) {
            case BACKEND_AUTO: return "Auto";
            case BACKEND_CPU: return "CPU";
            case BACKEND_GPU: return "GPU";
            case BACKEND_NNAPI: return "NNAPI";
            case BACKEND_COREML: return "CoreML";
            case BACKEND_ANE: return "ANE";
            case BACKEND_DELEGATE: return "Delegate";
            default: return "Unknown";
        }
    }

    /**
     * Check if NNAPI is available.
     */
    public boolean isNNApiAvailable() {
        return mNNApiAvailable;
    }

    /**
     * Check if GPU delegate is available.
     */
    public boolean isGpuDelegateAvailable() {
        return mGpuDelegateAvailable;
    }

    /**
     * Check if XNNPACK is available.
     */
    public boolean isXnnpackAvailable() {
        return mXnnpackAvailable;
    }

    /**
     * Get the NNAPI device name.
     */
    public String getNNApiDeviceName() {
        return mNNApiDeviceName;
    }

    /**
     * Get delegate options as JSON string.
     */
    public String getDelegateOptions() {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"nnapi\":").append(mNNApiAvailable);
        sb.append(",\"gpu\":").append(mGpuDelegateAvailable);
        sb.append(",\"xnnpack\":").append(mXnnpackAvailable);
        sb.append(",\"active_backend\":\"").append(getActiveBackendName()).append("\"");
        sb.append(",\"api_level\":").append(Build.VERSION.SDK_INT);
        sb.append(",\"nnapi_device\":\"").append(mNNApiDeviceName != null ? mNNApiDeviceName : "").append("\"");
        sb.append("}");
        return sb.toString();
    }

    /**
     * Release delegate resources.
     */
    public void release() {
        mAvailableBackends.clear();
        Log.i(TAG, "Delegate resources released");
    }
}