// Ainos AI Daemon - Semantic Cache
// 基于精确 prompt 匹配的 LRU 语义缓存
// 缓存推理结果，减少重复计算
// 使用 LRU 淘汰策略，最大缓存 1000 条
// 缓存键为 prompt + model + temperature 的组合哈希

use std::hash::{Hash, Hasher};
use std::num::NonZeroUsize;

/// 语义缓存
pub struct SemanticCache {
    cache: std::sync::Mutex<lru::LruCache<u64, String>>,
    hits: std::sync::atomic::AtomicU64,
    misses: std::sync::atomic::AtomicU64,
}

impl std::fmt::Debug for SemanticCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let cache = self.cache.lock().unwrap();
        f.debug_struct("SemanticCache")
            .field("len", &cache.len())
            .field("cap", &cache.cap())
            .field(
                "hits",
                &self.hits.load(std::sync::atomic::Ordering::Relaxed),
            )
            .field(
                "misses",
                &self.misses.load(std::sync::atomic::Ordering::Relaxed),
            )
            .finish()
    }
}

impl SemanticCache {
    /// 创建新的语义缓存，默认最大容量为 1000
    pub fn new() -> Self {
        Self::with_capacity(1000)
    }

    /// 创建指定容量的语义缓存
    pub fn with_capacity(capacity: usize) -> Self {
        // 确保容量至少为 1
        let cap = match NonZeroUsize::new(capacity) {
            Some(c) => c,
            None => NonZeroUsize::new(1000).unwrap(),
        };
        Self {
            cache: std::sync::Mutex::new(lru::LruCache::new(cap)),
            hits: std::sync::atomic::AtomicU64::new(0),
            misses: std::sync::atomic::AtomicU64::new(0),
        }
    }

    /// 计算缓存键
    /// 组合 prompt + model + temperature 的哈希
    /// temperature 使用定点量化避免浮点精度问题
    pub fn compute_key(prompt: &str, model: &str, temperature: f64) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        prompt.hash(&mut hasher);
        model.hash(&mut hasher);
        // 对 temperature 进行定点量化 (保留 3 位小数)
        let temp_quantized = (temperature * 1000.0) as i64;
        temp_quantized.hash(&mut hasher);
        hasher.finish()
    }

    /// 获取缓存条目
    pub fn get(&self, prompt: &str, model: &str, temperature: f64) -> Option<String> {
        let key = Self::compute_key(prompt, model, temperature);
        let mut cache = self.cache.lock().unwrap();
        if let Some(value) = cache.get(&key) {
            self.hits.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            Some(value.clone())
        } else {
            self.misses
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            None
        }
    }

    /// 存入缓存条目
    pub fn put(&self, prompt: &str, model: &str, temperature: f64, result: String) {
        let key = Self::compute_key(prompt, model, temperature);
        let mut cache = self.cache.lock().unwrap();
        cache.put(key, result);
    }

    /// 清空缓存
    pub fn clear(&self) {
        let mut cache = self.cache.lock().unwrap();
        cache.clear();
        self.hits.store(0, std::sync::atomic::Ordering::Relaxed);
        self.misses.store(0, std::sync::atomic::Ordering::Relaxed);
    }

    /// 当前缓存条目数
    pub fn len(&self) -> usize {
        let cache = self.cache.lock().unwrap();
        cache.len()
    }

    /// 缓存是否为空
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// 缓存容量上限
    pub fn capacity(&self) -> usize {
        let cache = self.cache.lock().unwrap();
        cache.cap().get()
    }

    /// 命中次数
    pub fn hits(&self) -> u64 {
        self.hits.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// 未命中次数
    pub fn misses(&self) -> u64 {
        self.misses.load(std::sync::atomic::Ordering::Relaxed)
    }

    /// 命中率 (0.0 ~ 1.0)
    pub fn hit_rate(&self) -> f64 {
        let hits = self.hits.load(std::sync::atomic::Ordering::Relaxed);
        let misses = self.misses.load(std::sync::atomic::Ordering::Relaxed);
        let total = hits + misses;
        if total == 0 {
            0.0
        } else {
            hits as f64 / total as f64
        }
    }
}

impl Default for SemanticCache {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_put_get() {
        let cache = SemanticCache::new();
        assert!(cache.is_empty());

        cache.put("hello", "model1", 0.7, "world".to_string());
        assert_eq!(cache.len(), 1);
        assert_eq!(cache.get("hello", "model1", 0.7), Some("world".to_string()));
    }

    #[test]
    fn test_cache_miss() {
        let cache = SemanticCache::new();
        assert_eq!(cache.get("nonexistent", "model1", 0.7), None);
    }

    #[test]
    fn test_cache_key_different_temp() {
        let cache = SemanticCache::new();
        cache.put("hello", "model1", 0.7, "result1".to_string());
        // 不同 temperature 应该产生不同的键
        assert_eq!(cache.get("hello", "model1", 0.8), None);
    }

    #[test]
    fn test_cache_key_quantization() {
        // 0.700 和 0.7 应该是相同的键
        let key1 = SemanticCache::compute_key("hello", "model1", 0.700);
        let key2 = SemanticCache::compute_key("hello", "model1", 0.7);
        assert_eq!(key1, key2);
    }

    #[test]
    fn test_cache_eviction() {
        let cache = SemanticCache::with_capacity(2);
        cache.put("a", "m", 0.5, "1".to_string());
        cache.put("b", "m", 0.5, "2".to_string());
        cache.put("c", "m", 0.5, "3".to_string()); // 应淘汰 "a"
        assert_eq!(cache.get("a", "m", 0.5), None);
        assert_eq!(cache.get("c", "m", 0.5), Some("3".to_string()));
    }

    #[test]
    fn test_hit_rate() {
        let cache = SemanticCache::new();
        assert_eq!(cache.hit_rate(), 0.0);
        cache.put("a", "m", 0.5, "1".to_string());
        cache.get("a", "m", 0.5); // hit
        cache.get("b", "m", 0.5); // miss
        assert!((cache.hit_rate() - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_clear() {
        let cache = SemanticCache::new();
        cache.put("a", "m", 0.5, "1".to_string());
        cache.put("b", "m", 0.5, "2".to_string());
        assert_eq!(cache.len(), 2);
        cache.clear();
        assert!(cache.is_empty());
        assert_eq!(cache.hits(), 0);
        assert_eq!(cache.misses(), 0);
    }
}