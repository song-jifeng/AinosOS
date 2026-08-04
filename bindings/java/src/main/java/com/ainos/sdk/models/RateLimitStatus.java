package com.ainos.sdk.models;

import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * Rate limit status for the current session.
 * <p>
 * Contains per-category rate limit information including the configured
 * limit, remaining requests, and reset time.
 * This class is immutable and thread-safe.
 */
public final class RateLimitStatus {

    private final List<RateLimitEntry> limits;

    /**
     * Constructs a new RateLimitStatus.
     *
     * @param limits list of per-category rate limit entries
     */
    public RateLimitStatus(List<RateLimitEntry> limits) {
        this.limits = limits != null
                ? Collections.unmodifiableList(limits)
                : Collections.emptyList();
    }

    /**
     * Creates an empty rate limit status.
     *
     * @return a RateLimitStatus with no limits
     */
    public static RateLimitStatus empty() {
        return new RateLimitStatus(Collections.emptyList());
    }

    /**
     * Returns the list of per-category rate limit entries.
     *
     * @return unmodifiable list of rate limit entries; may be empty
     */
    public List<RateLimitEntry> getLimits() {
        return limits;
    }

    /**
     * Returns the rate limit entry for a specific category, if present.
     *
     * @param category the category name (e.g. {@code "inference"}, {@code "model_ops"})
     * @return the matching entry, or empty if not found
     */
    public java.util.Optional<RateLimitEntry> getLimitFor(String category) {
        return limits.stream()
                .filter(e -> e.getCategory().equals(category))
                .findFirst();
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof RateLimitStatus)) return false;
        RateLimitStatus that = (RateLimitStatus) o;
        return limits.equals(that.limits);
    }

    @Override
    public int hashCode() {
        return Objects.hash(limits);
    }

    @Override
    public String toString() {
        return "RateLimitStatus{limits=" + limits + '}';
    }

    /**
     * A single rate limit entry for a specific operation category.
     */
    public static final class RateLimitEntry {
        private final String category;
        private final long limit;
        private final long remaining;
        private final long resetSeconds;

        public RateLimitEntry(String category, long limit, long remaining, long resetSeconds) {
            this.category = Objects.requireNonNull(category, "category must not be null");
            this.limit = limit;
            this.remaining = remaining;
            this.resetSeconds = resetSeconds;
        }

        /** Returns the operation category (e.g. {@code "inference"}, {@code "status"}). */
        public String getCategory() { return category; }

        /** Returns the maximum number of requests allowed within the window. */
        public long getLimit() { return limit; }

        /** Returns the number of requests remaining in the current window. */
        public long getRemaining() { return remaining; }

        /** Returns the seconds until the rate limit window resets. */
        public long getResetSeconds() { return resetSeconds; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof RateLimitEntry)) return false;
            RateLimitEntry that = (RateLimitEntry) o;
            return limit == that.limit && remaining == that.remaining
                    && resetSeconds == that.resetSeconds && category.equals(that.category);
        }

        @Override
        public int hashCode() {
            return Objects.hash(category, limit, remaining, resetSeconds);
        }

        @Override
        public String toString() {
            return "RateLimitEntry{category='" + category + "', limit=" + limit
                    + ", remaining=" + remaining + ", resetSeconds=" + resetSeconds + '}';
        }
    }
}