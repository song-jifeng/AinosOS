package com.ainos.models;

import android.util.Log;

/**
 * InferenceResult - Represents the result of a single inference execution.
 * Contains timing, token stats, and status information.
 */
public class InferenceResult {

    private static final String TAG = "InferenceResult";

    public final int status;
    public final byte[] outputData;
    public final int outputSize;
    public final float inferenceTimeMs;
    public final float preprocessTimeMs;
    public final float postprocessTimeMs;
    public final float totalTimeMs;
    public final long tokensGenerated;
    public final float tokensPerSecond;
    public final int thermalStatus;
    public final int batteryLevel;
    public final boolean wasThrottled;
    public final String errorMessage;

    /**
     * Create a successful inference result.
     */
    public InferenceResult(byte[] outputData, int outputSize,
                            float inferenceTimeMs, float totalTimeMs,
                            long tokensGenerated, float tokensPerSecond) {
        this.status = 0; // OK
        this.outputData = outputData;
        this.outputSize = outputSize;
        this.inferenceTimeMs = inferenceTimeMs;
        this.preprocessTimeMs = 0;
        this.postprocessTimeMs = 0;
        this.totalTimeMs = totalTimeMs;
        this.tokensGenerated = tokensGenerated;
        this.tokensPerSecond = tokensPerSecond;
        this.thermalStatus = 0; // Normal
        this.batteryLevel = 100;
        this.wasThrottled = false;
        this.errorMessage = "";
    }

    /**
     * Create a full inference result with all fields.
     */
    public InferenceResult(int status, byte[] outputData, int outputSize,
                            float inferenceTimeMs, float preprocessTimeMs,
                            float postprocessTimeMs, float totalTimeMs,
                            long tokensGenerated, float tokensPerSecond,
                            int thermalStatus, int batteryLevel,
                            boolean wasThrottled, String errorMessage) {
        this.status = status;
        this.outputData = outputData;
        this.outputSize = outputSize;
        this.inferenceTimeMs = inferenceTimeMs;
        this.preprocessTimeMs = preprocessTimeMs;
        this.postprocessTimeMs = postprocessTimeMs;
        this.totalTimeMs = totalTimeMs;
        this.tokensGenerated = tokensGenerated;
        this.tokensPerSecond = tokensPerSecond;
        this.thermalStatus = thermalStatus;
        this.batteryLevel = batteryLevel;
        this.wasThrottled = wasThrottled;
        this.errorMessage = errorMessage;
    }

    /**
     * Create an error result.
     */
    public static InferenceResult createError(int status, String errorMessage) {
        return new InferenceResult(
            status, null, 0,
            0, 0, 0, 0,
            0, 0,
            0, 0, false, errorMessage);
    }

    /**
     * Check if the inference was successful.
     */
    public boolean isSuccess() {
        return status == 0;
    }

    /**
     * Check if the inference was throttled.
     */
    public boolean isThrottled() {
        return wasThrottled;
    }

    /**
     * Get a human-readable status message.
     */
    public String getStatusMessage() {
        if (status == 0) return "Success";
        if (status == -9) return "Thermal Throttled";
        if (status == -10) return "Battery Low";
        if (status == -14) return "Inference Failed";
        if (status == -12) return "Model Load Failed";
        return "Error (" + status + ")";
    }

    @Override
    public String toString() {
        return "InferenceResult{" +
            "status=" + getStatusMessage() +
            ", inferenceTime=" + String.format("%.2f", inferenceTimeMs) + "ms" +
            ", totalTime=" + String.format("%.2f", totalTimeMs) + "ms" +
            ", tokens=" + tokensGenerated +
            ", tok/s=" + String.format("%.1f", tokensPerSecond) +
            ", throttled=" + wasThrottled +
            ", thermal=" + thermalStatus +
            ", battery=" + batteryLevel + "%" +
            '}';
    }
}