package com.ainos.sdk.models;

import java.util.Objects;

/**
 * Result of a health check against the Ainos daemon.
 * <p>
 * This class is immutable and thread-safe.
 */
public final class HealthStatus {

    private final boolean healthy;
    private final String message;
    private final long uptime;
    private final int modelsLoaded;
    private final boolean networkAvailable;

    /**
     * Constructs a new HealthStatus.
     *
     * @param healthy          whether the daemon is healthy
     * @param message          a human-readable status message
     * @param uptime           daemon uptime in seconds
     * @param modelsLoaded     number of loaded models
     * @param networkAvailable whether internet is reachable
     */
    public HealthStatus(boolean healthy, String message, long uptime,
                        int modelsLoaded, boolean networkAvailable) {
        this.healthy = healthy;
        this.message = Objects.requireNonNull(message, "message must not be null");
        this.uptime = uptime;
        this.modelsLoaded = modelsLoaded;
        this.networkAvailable = networkAvailable;
    }

    /**
     * Creates a healthy status.
     *
     * @return a healthy HealthStatus
     */
    public static HealthStatus healthy() {
        return new HealthStatus(true, "OK", 0, 0, false);
    }

    /**
     * Creates an unhealthy status with the given message.
     *
     * @param message the reason for being unhealthy
     * @return an unhealthy HealthStatus
     */
    public static HealthStatus unhealthy(String message) {
        return new HealthStatus(false, message, 0, 0, false);
    }

    /** Returns whether the daemon is healthy and responding. */
    public boolean isHealthy() {
        return healthy;
    }

    /** Returns a human-readable status message. */
    public String getMessage() {
        return message;
    }

    /** Returns the daemon uptime in seconds. */
    public long getUptime() {
        return uptime;
    }

    /** Returns the number of models currently loaded. */
    public int getModelsLoaded() {
        return modelsLoaded;
    }

    /** Returns whether the daemon has internet access. */
    public boolean isNetworkAvailable() {
        return networkAvailable;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof HealthStatus)) return false;
        HealthStatus that = (HealthStatus) o;
        return healthy == that.healthy
                && uptime == that.uptime
                && modelsLoaded == that.modelsLoaded
                && networkAvailable == that.networkAvailable
                && message.equals(that.message);
    }

    @Override
    public int hashCode() {
        return Objects.hash(healthy, message, uptime, modelsLoaded, networkAvailable);
    }

    @Override
    public String toString() {
        return "HealthStatus{"
                + "healthy=" + healthy
                + ", message='" + message + '\''
                + ", uptime=" + uptime
                + '}';
    }
}