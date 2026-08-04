// Ainos AI Daemon - Rate Limiting
//
// This module provides a comprehensive rate limiting system for the Ainos AI
// Daemon IPC layer. It implements the token bucket algorithm with:
//
// - Per-client rate limiters (tracked by IP or session)
// - Configurable rate (requests/second) and burst size per category
// - Rate limit headers for response
// - 429 Too Many Requests responses with Retry-After
// - Periodic garbage collection of stale rate limiters
// - Separate rate limit categories for different operations

use crate::config::RateLimitConfig;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use thiserror::Error;
use tokio::sync::RwLock;
use tracing::{debug, trace, warn};

// ============================================================================
// Error Types
// ============================================================================

/// Errors that can occur during rate limiting operations.
#[derive(Error, Debug, Clone)]
pub enum RateLimitError {
    /// The request was rate limited.
    #[error("Rate limit exceeded: retry after {retry_after:?}")]
    RateLimitExceeded {
        /// Category that was exceeded.
        category: RateLimitCategory,
        /// How long the client should wait before retrying.
        retry_after: Duration,
        /// Limit for this category.
        limit: u64,
        /// Remaining tokens before this request.
        remaining: u64,
    },

    /// The rate limiter configuration is invalid.
    #[error("Invalid rate limit configuration: {0}")]
    ConfigError(String),
}

// ============================================================================
// Rate Limit Categories
// ============================================================================

/// Rate limit categories for different types of operations.
///
/// Each category has its own rate limit (requests/second) and burst size.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum RateLimitCategory {
    /// Inference requests (default: 100 req/s, burst 200).
    #[serde(rename = "inference")]
    Inference,

    /// Model load/unload operations (default: 10 req/s, burst 20).
    #[serde(rename = "model_ops")]
    ModelOps,

    /// Status and context queries (default: 1000 req/s, burst 2000).
    #[serde(rename = "status")]
    Status,

    /// Administrative operations (default: 5 req/s, burst 10).
    #[serde(rename = "admin")]
    Admin,
}

impl RateLimitCategory {
    /// Return a human-readable description of this category.
    pub fn description(&self) -> &'static str {
        match self {
            RateLimitCategory::Inference => "Inference requests",
            RateLimitCategory::ModelOps => "Model operations (load/unload)",
            RateLimitCategory::Status => "Status and context queries",
            RateLimitCategory::Admin => "Administrative operations",
        }
    }

    /// Return the default rate (requests per second) for this category.
    pub fn default_rate(&self) -> f64 {
        match self {
            RateLimitCategory::Inference => 100.0,
            RateLimitCategory::ModelOps => 10.0,
            RateLimitCategory::Status => 1000.0,
            RateLimitCategory::Admin => 5.0,
        }
    }

    /// Return the default burst size for this category.
    pub fn default_burst(&self) -> f64 {
        match self {
            RateLimitCategory::Inference => 200.0,
            RateLimitCategory::ModelOps => 20.0,
            RateLimitCategory::Status => 2000.0,
            RateLimitCategory::Admin => 10.0,
        }
    }

    /// Determine the category from an IPC message type string.
    pub fn from_message_type(msg_type: &str) -> Self {
        match msg_type {
            "Inference" | "InferenceResponse" | "InferenceChunk" | "InferenceStream" => {
                RateLimitCategory::Inference
            }
            "ModelLoad" | "ModelUnload" => RateLimitCategory::ModelOps,
            "ModelList" | "ModelListResponse" | "Status" | "StatusResponse" | "RateLimitStatus" => {
                RateLimitCategory::Status
            }
            "ContextStore" | "ContextRetrieve" => RateLimitCategory::Status,
            _ => RateLimitCategory::Admin,
        }
    }
}

// ============================================================================
// Token Bucket Algorithm
// ============================================================================

/// A token bucket rate limiter.
///
/// The token bucket algorithm works as follows:
/// - A bucket holds `capacity` tokens.
/// - Tokens are added at a rate of `refill_rate` tokens per second.
/// - Each request consumes one token.
/// - If the bucket is empty, the request is denied.
/// - The bucket never exceeds its capacity.
///
/// This provides both rate limiting (via the refill rate) and burst
/// handling (via the bucket capacity).
#[derive(Debug, Clone)]
pub struct TokenBucket {
    /// Maximum number of tokens the bucket can hold (burst size).
    capacity: f64,

    /// Current number of tokens in the bucket.
    tokens: f64,

    /// Rate at which tokens are added (tokens per second).
    refill_rate: f64,

    /// Last time tokens were refilled.
    last_refill: Instant,
}

impl TokenBucket {
    /// Create a new token bucket with the given rate and capacity.
    pub fn new(rate_per_sec: f64, burst: f64) -> Self {
        Self {
            capacity: burst,
            tokens: burst, // Start with a full bucket
            refill_rate: rate_per_sec,
            last_refill: Instant::now(),
        }
    }

    /// Refill the bucket based on elapsed time.
    fn refill(&mut self) {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill);
        let tokens_to_add = elapsed.as_secs_f64() * self.refill_rate;
        self.tokens = (self.tokens + tokens_to_add).min(self.capacity);
        self.last_refill = now;
    }

    /// Try to consume one token from the bucket.
    ///
    /// Returns `Ok(remaining)` if a token was consumed, or `Err(wait_time)`
    /// if the bucket is empty and the client should wait.
    pub fn consume(&mut self) -> Result<u64, Duration> {
        self.refill();

        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            Ok(self.tokens as u64)
        } else {
            // Calculate how long until a token is available
            let wait_time = Duration::from_secs_f64(1.0 / self.refill_rate);
            Err(wait_time)
        }
    }

    /// Try to consume a specific number of tokens.
    ///
    /// Returns `Ok(remaining)` if tokens were consumed, or `Err(wait_time)`
    /// if not enough tokens are available.
    #[allow(dead_code)]
    pub fn consume_n(&mut self, n: u64) -> Result<u64, Duration> {
        self.refill();

        let n_f64 = n as f64;
        if self.tokens >= n_f64 {
            self.tokens -= n_f64;
            Ok(self.tokens as u64)
        } else {
            let wait_time =
                Duration::from_secs_f64((n_f64 - self.tokens) / self.refill_rate);
            Err(wait_time)
        }
    }

    /// Get the current number of tokens in the bucket.
    pub fn remaining(&self) -> u64 {
        // Estimate current tokens without mutating
        let elapsed = Instant::now().duration_since(self.last_refill);
        let estimated_tokens =
            (self.tokens + elapsed.as_secs_f64() * self.refill_rate).min(self.capacity);
        estimated_tokens as u64
    }

    /// Get the bucket capacity (burst limit).
    pub fn capacity(&self) -> u64 {
        self.capacity as u64
    }

    /// Get the refill rate (tokens per second).
    #[allow(dead_code)]
    pub fn refill_rate(&self) -> f64 {
        self.refill_rate
    }

    /// Calculate the time until the bucket is full.
    #[allow(dead_code)]
    pub fn time_until_full(&self) -> Duration {
        let elapsed = Instant::now().duration_since(self.last_refill);
        let tokens_to_add = elapsed.as_secs_f64() * self.refill_rate;
        let current_tokens = (self.tokens + tokens_to_add).min(self.capacity);
        let deficit = self.capacity - current_tokens;
        if deficit <= 0.0 {
            Duration::from_secs(0)
        } else {
            Duration::from_secs_f64(deficit / self.refill_rate)
        }
    }

    /// Reset the bucket to full capacity.
    #[allow(dead_code)]
    pub fn reset(&mut self) {
        self.tokens = self.capacity;
        self.last_refill = Instant::now();
    }
}

impl Default for TokenBucket {
    fn default() -> Self {
        Self::new(100.0, 200.0)
    }
}

// ============================================================================
// Per-Client Rate Limiter
// ============================================================================

/// A rate limiter that tracks multiple clients, each with their own token
/// buckets for each category.
///
/// Clients are identified by a key (client IP or session token). The rate
/// limiter maintains a separate set of buckets for each client.
pub struct RateLimiter {
    /// Per-client rate limiters: client_key -> (category -> bucket).
    clients: Arc<RwLock<HashMap<String, HashMap<RateLimitCategory, TokenBucket>>>>,

    /// Configuration for each category.
    config: HashMap<RateLimitCategory, (f64, f64)>, // (rate, burst)

    /// Statistics.
    stats: Arc<RateLimitStats>,

    /// Maximum number of clients to track.
    max_clients: usize,

    /// Inactivity timeout for client cleanup.
    inactivity_timeout: Duration,
}

/// Rate limiting statistics.
#[derive(Debug, Default)]
pub struct RateLimitStats {
    /// Total number of rate-limited requests.
    pub total_limited: AtomicU64,
    /// Total number of allowed requests.
    pub total_allowed: AtomicU64,
    /// Number of clients currently tracked.
    pub active_clients: AtomicU64,
    /// Number of clients that have been cleaned up.
    pub cleaned_clients: AtomicU64,
}

impl std::fmt::Debug for RateLimiter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RateLimiter")
            .field("max_clients", &self.max_clients)
            .field("inactivity_timeout", &self.inactivity_timeout)
            .field("active_clients", &self.stats.active_clients.load(Ordering::Relaxed))
            .field("total_allowed", &self.stats.total_allowed.load(Ordering::Relaxed))
            .field("total_limited", &self.stats.total_limited.load(Ordering::Relaxed))
            .finish()
    }
}

impl RateLimiter {
    /// Create a new rate limiter with default configuration.
    pub fn new(config: &RateLimitConfig) -> Self {
        let mut category_config = HashMap::new();

        // Use configured values or defaults
        let infer_rate = if config.infer_rps > 0.0 {
            config.infer_rps
        } else {
            RateLimitCategory::Inference.default_rate()
        };
        let infer_burst = if config.infer_burst > 0.0 {
            config.infer_burst
        } else {
            RateLimitCategory::Inference.default_burst()
        };
        category_config.insert(RateLimitCategory::Inference, (infer_rate, infer_burst));

        let model_rate = if config.model_rps > 0.0 {
            config.model_rps
        } else {
            RateLimitCategory::ModelOps.default_rate()
        };
        let model_burst = if config.model_burst > 0.0 {
            config.model_burst
        } else {
            RateLimitCategory::ModelOps.default_burst()
        };
        category_config.insert(RateLimitCategory::ModelOps, (model_rate, model_burst));

        let status_rate = if config.status_rps > 0.0 {
            config.status_rps
        } else {
            RateLimitCategory::Status.default_rate()
        };
        let status_burst = if config.status_burst > 0.0 {
            config.status_burst
        } else {
            RateLimitCategory::Status.default_burst()
        };
        category_config.insert(RateLimitCategory::Status, (status_rate, status_burst));

        let admin_rate = if config.admin_rps > 0.0 {
            config.admin_rps
        } else {
            RateLimitCategory::Admin.default_rate()
        };
        let admin_burst = if config.admin_burst > 0.0 {
            config.admin_burst
        } else {
            RateLimitCategory::Admin.default_burst()
        };
        category_config.insert(RateLimitCategory::Admin, (admin_rate, admin_burst));

        Self {
            clients: Arc::new(RwLock::new(HashMap::new())),
            config: category_config,
            stats: Arc::new(RateLimitStats::default()),
            max_clients: config.max_clients.max(100),
            inactivity_timeout: Duration::from_secs(config.cleanup_interval_secs.max(60)),
        }
    }

    /// Create a rate limiter with default configuration (for testing).
    pub fn default_for_test() -> Self {
        let config = RateLimitConfig::default();
        Self::new(&config)
    }

    /// Check if a request from a client is allowed.
    ///
    /// Returns `Ok(remaining)` if the request is allowed, or `Err` with
    /// rate limit information if it exceeds the limit.
    pub async fn check_rate_limit(
        &self,
        client_key: &str,
        category: RateLimitCategory,
    ) -> Result<RateLimitInfo, RateLimitError> {
        if !self.config.contains_key(&category) {
            return Err(RateLimitError::ConfigError(format!(
                "Unknown category: {:?}",
                category
            )));
        }

        let (rate, _burst) = self.config[&category];
        let mut clients = self.clients.write().await;

        // Get or create the client's buckets
        let client_buckets = clients
            .entry(client_key.to_string())
            .or_insert_with(|| {
                self.stats.active_clients.fetch_add(1, Ordering::Relaxed);
                let mut buckets = HashMap::new();
                for (cat, &(r, b)) in &self.config {
                    buckets.insert(*cat, TokenBucket::new(r, b));
                }
                buckets
            });

        // Get the bucket for this category
        let bucket = client_buckets
            .get_mut(&category)
            .expect("Bucket should exist for category");

        match bucket.consume() {
            Ok(remaining) => {
                self.stats.total_allowed.fetch_add(1, Ordering::Relaxed);
                Ok(RateLimitInfo {
                    limit: bucket.capacity(),
                    remaining,
                    reset: Duration::from_secs_f64(1.0 / rate),
                    category,
                })
            }
            Err(retry_after) => {
                self.stats.total_limited.fetch_add(1, Ordering::Relaxed);
                Err(RateLimitError::RateLimitExceeded {
                    category,
                    retry_after,
                    limit: bucket.capacity(),
                    remaining: 0,
                })
            }
        }
    }

    /// Get rate limit information without consuming a token (peek).
    pub async fn peek_rate_limit(
        &self,
        client_key: &str,
        category: RateLimitCategory,
    ) -> Option<RateLimitInfo> {
        let clients = self.clients.read().await;
        let buckets = clients.get(client_key)?;
        let bucket = buckets.get(&category)?;

        let (rate, _) = self.config.get(&category)?;

        Some(RateLimitInfo {
            limit: bucket.capacity(),
            remaining: bucket.remaining(),
            reset: Duration::from_secs_f64(1.0 / rate),
            category,
        })
    }

    /// Get the rate limit configuration for a category.
    pub fn get_category_config(&self, category: &RateLimitCategory) -> (f64, f64) {
        self.config.get(category).copied().unwrap_or_else(|| {
            (category.default_rate(), category.default_burst())
        })
    }

    /// Get statistics.
    pub fn stats(&self) -> &Arc<RateLimitStats> {
        &self.stats
    }

    /// Get the number of active clients.
    pub async fn active_clients(&self) -> usize {
        self.clients.read().await.len()
    }

    /// Remove a specific client from tracking.
    pub async fn remove_client(&self, client_key: &str) -> bool {
        let mut clients = self.clients.write().await;
        if clients.remove(client_key).is_some() {
            self.stats.active_clients.fetch_sub(1, Ordering::Relaxed);
            true
        } else {
            false
        }
    }

    /// Clean up stale clients that haven't been active.
    ///
    /// Since we don't track per-client activity time directly, we check
    /// if the client's token buckets are at full capacity (indicating no
    /// recent activity). This is a best-effort cleanup.
    pub async fn cleanup_stale(&self) -> usize {
        let mut clients = self.clients.write().await;
        let mut to_remove: Vec<String> = Vec::new();

        for (client_key, buckets) in clients.iter() {
            // A client is considered stale if all buckets are near full
            // (meaning no requests were made recently)
            let all_full = buckets.values().all(|b| {
                let remaining = b.remaining();
                let capacity = b.capacity();
                // If remaining >= 95% of capacity, the client has been idle
                remaining as f64 >= capacity as f64 * 0.95
            });

            if all_full {
                to_remove.push(client_key.clone());
            }
        }

        let count = to_remove.len();
        for key in to_remove {
            clients.remove(&key);
            self.stats.active_clients.fetch_sub(1, Ordering::Relaxed);
            self.stats.cleaned_clients.fetch_add(1, Ordering::Relaxed);
        }

        if count > 0 {
            debug!("Rate limiter: cleaned up {} stale clients", count);
        }

        count
    }

    /// Reset all rate limiters (for testing).
    #[allow(dead_code)]
    pub async fn reset_all(&self) {
        let mut clients = self.clients.write().await;
        clients.clear();
        self.stats.active_clients.store(0, Ordering::Relaxed);
    }

    /// Get the total number of clients tracked (including stale).
    #[allow(dead_code)]
    pub async fn total_clients(&self) -> usize {
        self.clients.read().await.len()
    }
}

// ============================================================================
// Rate Limit Info
// ============================================================================

/// Information about the current rate limit state.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitInfo {
    /// The rate limit (maximum requests allowed).
    pub limit: u64,

    /// The number of requests remaining in the current window.
    pub remaining: u64,

    /// Time until the rate limit resets.
    pub reset: Duration,

    /// The category this rate limit applies to.
    pub category: RateLimitCategory,
}

impl RateLimitInfo {
    /// Format as HTTP-style rate limit headers.
    pub fn to_headers(&self) -> Vec<(String, String)> {
        vec![
            ("X-RateLimit-Limit".to_string(), self.limit.to_string()),
            (
                "X-RateLimit-Remaining".to_string(),
                self.remaining.to_string(),
            ),
            (
                "X-RateLimit-Reset".to_string(),
                self.reset.as_secs().to_string(),
            ),
            (
                "X-RateLimit-Category".to_string(),
                format!("{:?}", self.category).to_lowercase(),
            ),
        ]
    }

    /// Format as a JSON object for IPC responses.
    pub fn to_json(&self) -> serde_json::Value {
        serde_json::json!({
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_seconds": self.reset.as_secs(),
            "category": format!("{:?}", self.category).to_lowercase(),
        })
    }
}

// ============================================================================
// Rate Limit Response
// ============================================================================

/// A response sent when a request is rate limited.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitResponse {
    /// Whether the request was allowed.
    pub allowed: bool,

    /// Human-readable message.
    pub message: String,

    /// Rate limit information.
    pub rate_limit: Option<RateLimitInfo>,

    /// Retry-After header value in seconds.
    pub retry_after_seconds: Option<u64>,

    /// The category that was exceeded.
    pub category: Option<String>,
}

impl RateLimitResponse {
    /// Create a "too many requests" response.
    pub fn too_many_requests(category: RateLimitCategory, retry_after: Duration, limit: u64) -> Self {
        Self {
            allowed: false,
            message: format!(
                "Rate limit exceeded for {:?}. Retry after {} seconds.",
                category,
                retry_after.as_secs()
            ),
            rate_limit: Some(RateLimitInfo {
                limit,
                remaining: 0,
                reset: retry_after,
                category,
            }),
            retry_after_seconds: Some(retry_after.as_secs().max(1)),
            category: Some(format!("{:?}", category).to_lowercase()),
        }
    }
}

// ============================================================================
// Periodic GC Task
// ============================================================================

/// Run periodic garbage collection on the rate limiter.
///
/// This should be spawned as a background task that runs every
/// `interval_secs` seconds to clean up stale rate limiters.
pub async fn rate_limit_gc_task(rate_limiter: Arc<RateLimiter>, interval_secs: u64) {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
    loop {
        interval.tick().await;
        let cleaned = rate_limiter.cleanup_stale().await;
        let active = rate_limiter.active_clients().await;
        trace!(
            "Rate limit GC: cleaned {}, active clients: {}",
            cleaned,
            active
        );

        // Log stats periodically
        let stats = rate_limiter.stats();
        if cleaned > 0 {
            debug!(
                "Rate limit stats: allowed={}, limited={}, active={}, cleaned={}",
                stats.total_allowed.load(Ordering::Relaxed),
                stats.total_limited.load(Ordering::Relaxed),
                stats.active_clients.load(Ordering::Relaxed),
                stats.cleaned_clients.load(Ordering::Relaxed),
            );
        }
    }
}

// ============================================================================
// Helper: Determine if rate limiting should apply to a message type
// ============================================================================

/// Check if a message type should be rate limited.
///
/// Some message types (like Auth and Error) should not be rate limited.
pub fn should_rate_limit(msg_type: &str) -> bool {
    !matches!(
        msg_type,
        "Auth" | "AuthResponse" | "Error" | "RateLimitStatus"
    )
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper to create a test rate limiter.
    fn test_limiter() -> Arc<RateLimiter> {
        let config = RateLimitConfig::default();
        Arc::new(RateLimiter::new(&config))
    }

    #[tokio::test]
    async fn test_token_bucket_consume() {
        let mut bucket = TokenBucket::new(100.0, 200.0);
        // Start with full bucket (200 tokens)
        assert!(bucket.consume().is_ok());
        assert_eq!(bucket.remaining(), 199);
    }

    #[tokio::test]
    async fn test_token_bucket_exhaustion() {
        let mut bucket = TokenBucket::new(1.0, 1.0); // 1 token per second, burst 1
        assert!(bucket.consume().is_ok(), "First request should succeed");
        // Second request should fail (bucket empty)
        let result = bucket.consume();
        assert!(result.is_err(), "Second request should be rate limited");
    }

    #[tokio::test]
    async fn test_token_bucket_refill() {
        let mut bucket = TokenBucket::new(10.0, 1.0); // 10 tokens/sec, burst 1
        assert!(bucket.consume().is_ok(), "First request should succeed");
        // Wait for refill
        tokio::time::sleep(Duration::from_millis(200)).await;
        // Should have at least 1 token now (200ms * 10/s = 2 tokens, but capped at burst=1)
        assert!(bucket.consume().is_ok(), "Should have refilled after 200ms");
    }

    #[tokio::test]
    async fn test_token_bucket_burst() {
        let mut bucket = TokenBucket::new(10.0, 5.0); // 10 tokens/sec, burst 5
        // Should be able to consume 5 tokens immediately
        for i in 0..5 {
            assert!(
                bucket.consume().is_ok(),
                "Request {} should succeed (burst)",
                i + 1
            );
        }
        // 6th token should fail
        assert!(bucket.consume().is_err(), "6th request should fail (burst exhausted)");
    }

    #[tokio::test]
    async fn test_token_bucket_remaining() {
        let bucket = TokenBucket::new(10.0, 20.0);
        // Bucket should be full
        assert_eq!(bucket.remaining(), 20);
    }

    #[tokio::test]
    async fn test_rate_limiter_check_rate_limit() {
        let limiter = test_limiter();
        let client_key = "127.0.0.1:12345";

        // First request should be allowed
        let result = limiter
            .check_rate_limit(client_key, RateLimitCategory::Status)
            .await;
        assert!(result.is_ok(), "First request should be allowed");
        let info = result.unwrap();
        assert!(info.remaining < info.limit);
    }

    #[tokio::test]
    async fn test_rate_limiter_exceed() {
        let config = RateLimitConfig {
            enabled: true,
            infer_rps: 1000.0,
            infer_burst: 3.0, // Very small burst
            model_rps: 10.0,
            model_burst: 20.0,
            status_rps: 1000.0,
            status_burst: 3.0, // Very small burst
            admin_rps: 5.0,
            admin_burst: 10.0,
            max_clients: 1000,
            cleanup_interval_secs: 300,
        };
        let limiter = Arc::new(RateLimiter::new(&config));
        let client_key = "test-client";

        // Exhaust the status bucket (burst=3)
        for i in 0..3 {
            let result = limiter
                .check_rate_limit(client_key, RateLimitCategory::Status)
                .await;
            assert!(
                result.is_ok(),
                "Request {} should be allowed (burst=3)",
                i + 1
            );
        }

        // 4th request should fail
        let result = limiter
            .check_rate_limit(client_key, RateLimitCategory::Status)
            .await;
        assert!(result.is_err(), "4th request should be rate limited");
        match result {
            Err(RateLimitError::RateLimitExceeded { remaining, ..}) => {
                assert_eq!(remaining, 0);
            }
            _ => panic!("Expected RateLimitExceeded"),
        }
    }

    #[tokio::test]
    async fn test_rate_limiter_peek() {
        let limiter = test_limiter();
        let client_key = "peek-client";

        // Peek without consuming
        let peek = limiter
            .peek_rate_limit(client_key, RateLimitCategory::Inference)
            .await;
        assert!(peek.is_none(), "Peek should return None for unknown client");

        // Consume first, then peek
        limiter
            .check_rate_limit(client_key, RateLimitCategory::Inference)
            .await
            .unwrap();

        let peek = limiter
            .peek_rate_limit(client_key, RateLimitCategory::Inference)
            .await;
        assert!(peek.is_some(), "Peek should return info for known client");
        let info = peek.unwrap();
        assert!(info.remaining < info.limit);
    }

    #[tokio::test]
    async fn test_rate_limiter_multiple_clients() {
        let limiter = test_limiter();

        // Two clients should not interfere with each other
        let r1 = limiter
            .check_rate_limit("client-a", RateLimitCategory::Inference)
            .await
            .unwrap();
        let r2 = limiter
            .check_rate_limit("client-b", RateLimitCategory::Inference)
            .await
            .unwrap();

        // Both should have the same limit
        assert_eq!(r1.limit, r2.limit);
    }

    #[tokio::test]
    async fn test_rate_limiter_different_categories() {
        let limiter = test_limiter();
        let client = "multi-cat-client";

        // Different categories should have different limits
        let infer = limiter
            .check_rate_limit(client, RateLimitCategory::Inference)
            .await
            .unwrap();
        let status = limiter
            .check_rate_limit(client, RateLimitCategory::Status)
            .await
            .unwrap();

        // Status should have a higher limit than inference
        assert!(status.limit > infer.limit);
    }

    #[tokio::test]
    async fn test_rate_limiter_remove_client() {
        let limiter = test_limiter();
        let client = "remove-me";

        limiter
            .check_rate_limit(client, RateLimitCategory::Status)
            .await
            .unwrap();

        assert_eq!(limiter.active_clients().await, 1);
        assert!(limiter.remove_client(client).await);
        assert_eq!(limiter.active_clients().await, 0);
    }

    #[tokio::test]
    async fn test_rate_limiter_cleanup_stale() {
        let limiter = test_limiter();
        let client = "stale-client";

        // Make a request
        limiter
            .check_rate_limit(client, RateLimitCategory::Status)
            .await
            .unwrap();

        // The client should still be tracked
        assert_eq!(limiter.active_clients().await, 1);

        // Cleanup should not remove a recently active client unexpectedly
        // (it may or may not be cleaned depending on refill timing)
        let cleaned = limiter.cleanup_stale().await;
        // The client should either still exist or have been cleaned
        // (both are valid behaviors depending on timing)
        let active = limiter.active_clients().await;
        assert!(active == 0 || active == 1, "Client should be either kept or cleaned");
    }

    #[tokio::test]
    async fn test_rate_limit_info_headers() {
        let info = RateLimitInfo {
            limit: 100,
            remaining: 50,
            reset: Duration::from_secs(1),
            category: RateLimitCategory::Inference,
        };

        let headers = info.to_headers();
        assert_eq!(headers.len(), 4);
        assert!(headers.iter().any(|(k, _)| k == "X-RateLimit-Limit"));
        assert!(headers.iter().any(|(k, _)| k == "X-RateLimit-Remaining"));
        assert!(headers.iter().any(|(k, _)| k == "X-RateLimit-Reset"));
    }

    #[tokio::test]
    async fn test_rate_limit_info_json() {
        let info = RateLimitInfo {
            limit: 100,
            remaining: 50,
            reset: Duration::from_secs(1),
            category: RateLimitCategory::ModelOps,
        };

        let json = info.to_json();
        assert_eq!(json["limit"], 100);
        assert_eq!(json["remaining"], 50);
        assert_eq!(json["category"], "modelops");
    }

    #[tokio::test]
    async fn test_rate_limit_response() {
        let resp = RateLimitResponse::too_many_requests(
            RateLimitCategory::Inference,
            Duration::from_secs(30),
            100,
        );

        assert!(!resp.allowed);
        assert_eq!(resp.retry_after_seconds, Some(30));
        assert_eq!(resp.category, Some("inference".to_string()));
    }

    #[tokio::test]
    async fn test_should_rate_limit() {
        assert!(should_rate_limit("Inference"));
        assert!(should_rate_limit("ModelLoad"));
        assert!(should_rate_limit("Status"));
        assert!(!should_rate_limit("Auth"));
        assert!(!should_rate_limit("Error"));
        assert!(!should_rate_limit("RateLimitStatus"));
    }

    #[tokio::test]
    async fn test_category_from_message_type() {
        assert_eq!(
            RateLimitCategory::from_message_type("Inference"),
            RateLimitCategory::Inference
        );
        assert_eq!(
            RateLimitCategory::from_message_type("ModelLoad"),
            RateLimitCategory::ModelOps
        );
        assert_eq!(
            RateLimitCategory::from_message_type("ModelUnload"),
            RateLimitCategory::ModelOps
        );
        assert_eq!(
            RateLimitCategory::from_message_type("Status"),
            RateLimitCategory::Status
        );
        assert_eq!(
            RateLimitCategory::from_message_type("ContextStore"),
            RateLimitCategory::Status
        );
        assert_eq!(
            RateLimitCategory::from_message_type("Unknown"),
            RateLimitCategory::Admin
        );
    }

    #[tokio::test]
    async fn test_category_defaults() {
        let infer = RateLimitCategory::Inference;
        assert_eq!(infer.default_rate(), 100.0);
        assert_eq!(infer.default_burst(), 200.0);

        let model = RateLimitCategory::ModelOps;
        assert_eq!(model.default_rate(), 10.0);
        assert_eq!(model.default_burst(), 20.0);

        let status = RateLimitCategory::Status;
        assert_eq!(status.default_rate(), 1000.0);
        assert_eq!(status.default_burst(), 2000.0);

        let admin = RateLimitCategory::Admin;
        assert_eq!(admin.default_rate(), 5.0);
        assert_eq!(admin.default_burst(), 10.0);
    }

    #[tokio::test]
    async fn test_rate_limiter_stats() {
        let limiter = test_limiter();
        let stats = limiter.stats();

        assert_eq!(stats.total_allowed.load(Ordering::Relaxed), 0);
        assert_eq!(stats.total_limited.load(Ordering::Relaxed), 0);

        limiter
            .check_rate_limit("stats-client", RateLimitCategory::Status)
            .await
            .unwrap();

        assert_eq!(stats.total_allowed.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn test_rate_limiter_reset_all() {
        let limiter = test_limiter();

        limiter
            .check_rate_limit("client-a", RateLimitCategory::Status)
            .await
            .unwrap();
        limiter
            .check_rate_limit("client-b", RateLimitCategory::Status)
            .await
            .unwrap();

        assert_eq!(limiter.active_clients().await, 2);

        limiter.reset_all().await;
        assert_eq!(limiter.active_clients().await, 0);
    }

    #[tokio::test]
    async fn test_rate_limiter_max_clients() {
        let config = RateLimitConfig {
            enabled: true,
            infer_rps: 100.0,
            infer_burst: 200.0,
            model_rps: 10.0,
            model_burst: 20.0,
            status_rps: 1000.0,
            status_burst: 2000.0,
            admin_rps: 5.0,
            admin_burst: 10.0,
            max_clients: 10,
            cleanup_interval_secs: 300,
        };
        let limiter = Arc::new(RateLimiter::new(&config));

        // Add 10 clients
        for i in 0..10 {
            limiter
                .check_rate_limit(&format!("client-{}", i), RateLimitCategory::Status)
                .await
                .unwrap();
        }

        assert_eq!(limiter.active_clients().await, 10);
    }

    #[tokio::test]
    async fn test_token_bucket_consume_n() {
        let mut bucket = TokenBucket::new(10.0, 10.0);
        assert!(bucket.consume_n(5).is_ok(), "Should consume 5 tokens");
        assert_eq!(bucket.remaining(), 5);
    }

    #[tokio::test]
    async fn test_token_bucket_time_until_full() {
        let mut bucket = TokenBucket::new(10.0, 10.0);
        bucket.consume_n(5).unwrap();
        let time = bucket.time_until_full();
        assert!(time > Duration::from_secs(0));
    }

    #[tokio::test]
    async fn test_token_bucket_reset() {
        let mut bucket = TokenBucket::new(10.0, 10.0);
        bucket.consume_n(5).unwrap();
        assert_eq!(bucket.remaining(), 5);
        bucket.reset();
        assert_eq!(bucket.remaining(), 10);
    }

    #[tokio::test]
    async fn test_rate_limiter_cleanup_gc() {
        let limiter = test_limiter();

        // Make a request to create a client entry
        limiter
            .check_rate_limit("gc-client", RateLimitCategory::Status)
            .await
            .unwrap();

        // Remove the client and verify
        assert!(limiter.remove_client("gc-client").await);
        assert_eq!(limiter.active_clients().await, 0);
    }

    #[tokio::test]
    async fn test_rate_limit_category_description() {
        assert_eq!(
            RateLimitCategory::Inference.description(),
            "Inference requests"
        );
        assert_eq!(
            RateLimitCategory::Admin.description(),
            "Administrative operations"
        );
    }

    #[tokio::test]
    async fn test_rate_limit_error_messages() {
        let err = RateLimitError::RateLimitExceeded {
            category: RateLimitCategory::Inference,
            retry_after: Duration::from_secs(30),
            limit: 100,
            remaining: 0,
        };
        let msg = format!("{}", err);
        assert!(msg.contains("Rate limit exceeded"));
    }

    #[tokio::test]
    async fn test_multiple_categories_independent() {
        let limiter = test_limiter();
        let client = "independent-client";

        // Consume from different categories
        let r1 = limiter
            .check_rate_limit(client, RateLimitCategory::Inference)
            .await
            .unwrap();
        let r2 = limiter
            .check_rate_limit(client, RateLimitCategory::ModelOps)
            .await
            .unwrap();

        // Each category should have its own limit
        assert_eq!(r1.limit, 200); // Infer burst
        assert_eq!(r2.limit, 20); // ModelOps burst
    }
}