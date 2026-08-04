package com.ainos.models;

import android.util.Log;

import java.util.Arrays;

/**
 * ModelInfo - Represents an AI model available on the Ainos platform.
 * Carries metadata about the model including format, size, precision, and state.
 */
public class ModelInfo {

    private static final String TAG = "ModelInfo";

    // Model format constants
    public static final int FORMAT_UNKNOWN = 0;
    public static final int FORMAT_TFLITE = 1;
    public static final int FORMAT_COREML = 2;
    public static final int FORMAT_ONNX = 3;
    public static final int FORMAT_SAFETENSORS = 4;

    // Model type constants
    public static final int TYPE_UNKNOWN = 0;
    public static final int TYPE_LLM = 1;
    public static final int TYPE_VISION = 2;
    public static final int TYPE_AUDIO = 3;
    public static final int TYPE_EMBEDDING = 4;
    public static final int TYPE_MULTIMODAL = 5;

    // State constants
    public static final int STATE_NOT_DOWNLOADED = 0;
    public static final int STATE_DOWNLOADING = 1;
    public static final int STATE_DOWNLOADED = 2;
    public static final int STATE_LOADING = 3;
    public static final int STATE_LOADED = 4;
    public static final int STATE_ERROR = 5;
    public static final int STATE_OBSOLETE = 6;

    // Precision constants
    public static final int PRECISION_FP32 = 0;
    public static final int PRECISION_FP16 = 1;
    public static final int PRECISION_INT8 = 2;
    public static final int PRECISION_INT4 = 3;
    public static final int PRECISION_MIXED = 4;

    public final String modelId;
    public final String modelName;
    public String modelVersion;
    public int format;
    public int type;
    public int precision;
    public int state;
    public long fileSize;
    public long downloadProgress;
    public long parameterCount;
    public float modelSizeMb;
    public float requiredRamMb;
    public float requiredStorageMb;
    public String checksumSha256;
    public String downloadUrl;
    public String modelPath;
    public String cachePath;
    public long lastUsedTimestamp;
    public long downloadTimestamp;
    public boolean isBundled;
    public boolean requiresNetwork;
    public boolean isEncrypted;
    public String errorMessage;

    /**
     * Create a new ModelInfo.
     */
    public ModelInfo(String modelId, String modelName, int format) {
        this.modelId = modelId;
        this.modelName = modelName;
        this.format = format;
        this.modelVersion = "1.0.0";
        this.state = STATE_NOT_DOWNLOADED;
        this.downloadProgress = 0;
        this.lastUsedTimestamp = 0;
        this.downloadTimestamp = 0;
        this.isBundled = false;
        this.requiresNetwork = true;
        this.isEncrypted = false;
        this.errorMessage = "";
        this.checksumSha256 = "";
        this.downloadUrl = "";
        this.modelPath = "";
        this.cachePath = "";
    }

    /**
     * Create a default LLM model configuration.
     */
    public static ModelInfo createLLM(String modelId, String name, int precision,
                                       float sizeMb, float ramMb, long paramCount) {
        ModelInfo info = new ModelInfo(modelId, name, FORMAT_TFLITE);
        info.type = TYPE_LLM;
        info.precision = precision;
        info.modelSizeMb = sizeMb;
        info.requiredRamMb = ramMb;
        info.requiredStorageMb = sizeMb * 1.2f;
        info.parameterCount = paramCount;
        info.fileSize = (long)(sizeMb * 1024 * 1024);
        return info;
    }

    /**
     * Create a default vision model configuration.
     */
    public static ModelInfo createVision(String modelId, String name, int precision,
                                          float sizeMb, float ramMb) {
        ModelInfo info = new ModelInfo(modelId, name, FORMAT_TFLITE);
        info.type = TYPE_VISION;
        info.precision = precision;
        info.modelSizeMb = sizeMb;
        info.requiredRamMb = ramMb;
        info.requiredStorageMb = sizeMb * 1.2f;
        info.fileSize = (long)(sizeMb * 1024 * 1024);
        return info;
    }

    /**
     * Create a default embedding model configuration.
     */
    public static ModelInfo createEmbedding(String modelId, String name, int precision,
                                             float sizeMb, float ramMb) {
        ModelInfo info = new ModelInfo(modelId, name, FORMAT_ONNX);
        info.type = TYPE_EMBEDDING;
        info.precision = precision;
        info.modelSizeMb = sizeMb;
        info.requiredRamMb = ramMb;
        info.requiredStorageMb = sizeMb * 1.2f;
        info.fileSize = (long)(sizeMb * 1024 * 1024);
        return info;
    }

    /**
     * Check if the model is downloaded.
     */
    public boolean isDownloaded() {
        return state == STATE_DOWNLOADED || state == STATE_LOADED;
    }

    /**
     * Check if the model is loaded in memory.
     */
    public boolean isLoaded() {
        return state == STATE_LOADED;
    }

    /**
     * Check if the model is currently downloading.
     */
    public boolean isDownloading() {
        return state == STATE_DOWNLOADING;
    }

    /**
     * Get the download progress as a percentage (0.0 - 1.0).
     */
    public float getDownloadProgressPercent() {
        if (fileSize <= 0) return 0.0f;
        return (float) downloadProgress / (float) fileSize;
    }

    /**
     * Get formatted model size string.
     */
    public String getFormattedSize() {
        if (modelSizeMb < 1.0f) {
            return String.format("%.0f KB", modelSizeMb * 1024.0f);
        } else if (modelSizeMb < 1024.0f) {
            return String.format("%.1f MB", modelSizeMb);
        } else {
            return String.format("%.2f GB", modelSizeMb / 1024.0f);
        }
    }

    /**
     * Get the format as a display string.
     */
    public String getFormatString() {
        switch (format) {
            case FORMAT_TFLITE: return "TFLite";
            case FORMAT_COREML: return "CoreML";
            case FORMAT_ONNX: return "ONNX";
            case FORMAT_SAFETENSORS: return "SafeTensors";
            default: return "Unknown";
        }
    }

    /**
     * Get the type as a display string.
     */
    public String getTypeString() {
        switch (type) {
            case TYPE_LLM: return "LLM (Text)";
            case TYPE_VISION: return "Vision";
            case TYPE_AUDIO: return "Audio";
            case TYPE_EMBEDDING: return "Embedding";
            case TYPE_MULTIMODAL: return "Multimodal";
            default: return "Unknown";
        }
    }

    /**
     * Get the state as a display string.
     */
    public String getStateString() {
        switch (state) {
            case STATE_NOT_DOWNLOADED: return "Not Downloaded";
            case STATE_DOWNLOADING: return "Downloading";
            case STATE_DOWNLOADED: return "Downloaded";
            case STATE_LOADING: return "Loading";
            case STATE_LOADED: return "Loaded";
            case STATE_ERROR: return "Error";
            case STATE_OBSOLETE: return "Obsolete";
            default: return "Unknown";
        }
    }

    /**
     * Get the precision as a display string.
     */
    public String getPrecisionString() {
        switch (precision) {
            case PRECISION_FP32: return "FP32";
            case PRECISION_FP16: return "FP16";
            case PRECISION_INT8: return "INT8";
            case PRECISION_INT4: return "INT4";
            case PRECISION_MIXED: return "Mixed";
            default: return "Unknown";
        }
    }

    /**
     * Get the parameter count as a display string.
     */
    public String getParameterCountString() {
        if (parameterCount >= 1_000_000_000) {
            return String.format("%.1fB", parameterCount / 1_000_000_000.0);
        } else if (parameterCount >= 1_000_000) {
            return String.format("%.1fM", parameterCount / 1_000_000.0);
        } else if (parameterCount >= 1_000) {
            return String.format("%.1fK", parameterCount / 1_000.0);
        }
        return String.valueOf(parameterCount);
    }

    @Override
    public String toString() {
        return "ModelInfo{" +
            "modelId='" + modelId + '\'' +
            ", modelName='" + modelName + '\'' +
            ", type=" + getTypeString() +
            ", format=" + getFormatString() +
            ", precision=" + getPrecisionString() +
            ", state=" + getStateString() +
            ", size=" + getFormattedSize() +
            ", params=" + getParameterCountString() +
            '}';
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        ModelInfo modelInfo = (ModelInfo) o;
        return modelId.equals(modelInfo.modelId);
    }

    @Override
    public int hashCode() {
        return modelId.hashCode();
    }
}