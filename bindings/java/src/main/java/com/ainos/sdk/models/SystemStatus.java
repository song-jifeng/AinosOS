package com.ainos.sdk.models;

import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Daemon health and statistics.
 * <p>
 * Provides information about the daemon's runtime status, including
 * uptime, loaded models, request counts, and network availability.
 * This class is immutable and thread-safe.
 */
public final class SystemStatus {

    private final long uptime;
    private final int modelsLoaded;
    private final long totalRequests;
    private final boolean networkAvailable;
    private final int activeSessions;
    private final List<RateLimitInfo> rateLimits;

    /**
     * Constructs a new SystemStatus instance.
     *
     * @param uptime           seconds since the daemon started
     * @param modelsLoaded     number of models currently loaded in memory
     * @param totalRequests    total inference requests handled
     * @param networkAvailable whether the internet is reachable
     * @param activeSessions   number of active client sessions
     * @param rateLimits       list of rate limit status entries (may be empty)
     */
    public SystemStatus(long uptime, int modelsLoaded, long totalRequests,
                        boolean networkAvailable, int activeSessions,
                        List<RateLimitInfo> rateLimits) {
        this.uptime = uptime;
        this.modelsLoaded = modelsLoaded;
        this.totalRequests = totalRequests;
        this.networkAvailable = networkAvailable;
        this.activeSessions = activeSessions;
        this.rateLimits = rateLimits != null
                ? Collections.unmodifiableList(rateLimits)
                : Collections.emptyList();
    }

    /**
     * Creates a minimal SystemStatus with default values.
     *
     * @return a "zeroed" SystemStatus
     */
    public static SystemStatus empty() {
        return new SystemStatus(0, 0, 0, false, 0, Collections.emptyList());
    }

    /** Returns the seconds since the daemon started. */
    public long getUptime() {
        return uptime;
    }

    /** Returns the number of models currently loaded in memory. */
    public int getModelsLoaded() {
        return modelsLoaded;
    }

    /** Returns the total number of inference requests handled. */
    public long getTotalRequests() {
        return totalRequests;
    }

    /** Returns whether the internet is reachable from the daemon. */
    public boolean isNetworkAvailable() {
        return networkAvailable;
    }

    /** Returns the number of active client sessions. */
    public int getActiveSessions() {
        return activeSessions;
    }

    /**
     * Returns the list of rate limit status entries for the current session.
     *
     * @return unmodifiable list of rate limit info; may be empty
     */
    public List<RateLimitInfo> getRateLimits() {
        return rateLimits;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof SystemStatus)) return false;
        SystemStatus that = (SystemStatus) o;
        return uptime == that.uptime
                && modelsLoaded == that.modelsLoaded
                && totalRequests == that.totalRequests
                && networkAvailable == that.networkAvailable
                && activeSessions == that.activeSessions
                && Objects.equals(rateLimits, that.rateLimits);
    }

    @Override
    public int hashCode() {
        return Objects.hash(uptime, modelsLoaded, totalRequests, networkAvailable, activeSessions, rateLimits);
    }

    @Override
    public String toString() {
        return "SystemStatus{"
                + "uptime=" + uptime
                + "s, modelsLoaded=" + modelsLoaded
                + ", totalRequests=" + totalRequests
                + ", networkAvailable=" + networkAvailable
                + ", activeSessions=" + activeSessions
                + '}';
    }

    /**
     * Rate limit information for a specific operation category.
     */
    public static final class RateLimitInfo {
        private final String category;
        private final long limit;
        private final long remaining;
        private final long resetSeconds;

        public RateLimitInfo(String category, long limit, long remaining, long resetSeconds) {
            this.category = Objects.requireNonNull(category);
            this.limit = limit;
            this.remaining = remaining;
            this.resetSeconds = resetSeconds;
        }

        public String getCategory() { return category; }
        public long getLimit() { return limit; }
        public long getRemaining() { return remaining; }
        public long getResetSeconds() { return resetSeconds; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof RateLimitInfo)) return false;
            RateLimitInfo that = (RateLimitInfo) o;
            return limit == that.limit && remaining == that.remaining
                    && resetSeconds == that.resetSeconds && category.equals(that.category);
        }

        @Override
        public int hashCode() {
            return Objects.hash(category, limit, remaining, resetSeconds);
        }

        @Override
        public String toString() {
            return "RateLimitInfo{category='" + category + "', limit=" + limit
                    + ", remaining=" + remaining + ", resetSeconds=" + resetSeconds + '}';
        }
    }
}