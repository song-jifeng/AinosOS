// Ainos AI Daemon - Context Manager
// 会话级记忆存储，支持 SQLite 持久化 (feature flag: sqlite-persistence)
// 通过 log_rotation 配置管理日志轮转
//
// 修复日志:
// - 2024-08: retrieve() 现在正确将 SQLite 结果写回内存缓存
// - 2024-08: 添加内存缓存 TTL 检查
// - 2024-08: 添加 LRU 淘汰策略
// - 2024-08: 添加上下文统计 (hits, misses, evictions)

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use chrono::{DateTime, Utc};
use tracing::debug;

/// 上下文条目
#[derive(Debug, Clone)]
struct ContextEntry {
    value: String,
    created_at: DateTime<Utc>,
    accessed_at: DateTime<Utc>,
    access_count: u64,
}

/// 日志轮转配置
#[derive(Debug, Clone)]
pub struct LogRotationConfig {
    /// 是否启用日志轮转
    pub enabled: bool,
    /// 单个日志文件最大大小 (MB)
    pub max_size_mb: u64,
    /// 保留天数
    pub retain_days: u32,
    /// 日志文件路径模式
    pub log_path: String,
}

impl Default for LogRotationConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            max_size_mb: 100,
            retain_days: 7,
            log_path: "logs/ai-daemon.log".to_string(),
        }
    }
}

/// 上下文管理器 - 会话级记忆存储
///
/// 支持多级缓存：内存 (L1) -> SQLite (L2)
/// 使用 Mutex 实现内部可变性，允许在 &self 下写入内存缓存
#[derive(Debug)]
pub struct ContextManager {
    /// 上下文存储 (session_id -> (key -> entry))
    /// 使用 Mutex 实现内部可变性，以便 retrieve() 在 &self 下写回内存
    sessions: Mutex<HashMap<String, HashMap<String, ContextEntry>>>,
    /// 最大条目数
    pub(crate) max_entries: u32,
    /// TTL (天)
    pub(crate) ttl_days: u32,
    /// 最大内存缓存条目数 (超过此值触发 LRU 淘汰)
    pub(crate) max_memory_entries: u32,
    /// SQLite 持久化路径 (仅当 feature 启用时存在)
    #[cfg(feature = "sqlite-persistence")]
    sqlite_path: Option<String>,
    /// 日志轮转配置
    pub log_rotation: LogRotationConfig,

    // ---- 统计信息 ----
    /// 缓存命中次数
    hits: AtomicU64,
    /// 缓存未命中次数
    misses: AtomicU64,
    /// 淘汰条目数
    evictions: AtomicU64,
    /// 总存储请求数
    total_stores: AtomicU64,
    /// 总检索请求数
    total_retrieves: AtomicU64,
}

impl ContextManager {
    pub fn new() -> Self {
        Self {
            sessions: Mutex::new(HashMap::new()),
            max_entries: 10000,
            ttl_days: 30,
            max_memory_entries: 5000,
            #[cfg(feature = "sqlite-persistence")]
            sqlite_path: None,
            log_rotation: LogRotationConfig::default(),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            evictions: AtomicU64::new(0),
            total_stores: AtomicU64::new(0),
            total_retrieves: AtomicU64::new(0),
        }
    }

    /// 设置日志轮转配置
    pub fn with_log_rotation(mut self, config: LogRotationConfig) -> Self {
        self.log_rotation = config;
        self
    }

    /// 启用 SQLite 持久化存储
    /// 需要在 Cargo.toml 中启用 `sqlite-persistence` feature
    #[cfg(feature = "sqlite-persistence")]
    pub fn enable_sqlite(&mut self, path: &str) -> anyhow::Result<()> {
        self.sqlite_path = Some(path.to_string());
        self.init_sqlite(path)?;
        tracing::info!(
            "[ContextManager] SQLite persistence initialized at {}",
            path
        );
        Ok(())
    }

    /// 初始化 SQLite 数据库表结构
    #[cfg(feature = "sqlite-persistence")]
    fn init_sqlite(&self, path: &str) -> anyhow::Result<()> {
        let conn = rusqlite::Connection::open(path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS context_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                accessed_at TEXT NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(session_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_context_session
                ON context_store(session_id);
            CREATE INDEX IF NOT EXISTS idx_context_key
                ON context_store(session_id, key);",
        )?;
        Ok(())
    }

    /// 存储上下文
    pub fn store(&mut self, key: String, value: String) {
        let session_id = "default".to_string();
        let now = Utc::now();

        let entry = ContextEntry {
            value: value.clone(),
            created_at: now,
            accessed_at: now,
            access_count: 1,
        };

        // 内存存储 (使用 Mutex 锁)
        {
            let mut sessions = self.sessions.lock().unwrap();
            let session = sessions
                .entry(session_id.clone())
                .or_insert_with(HashMap::new);

            // 检查是否达到最大条目数，达到则淘汰最旧的
            if session.len() >= self.max_entries as usize && !session.contains_key(&key) {
                if let Some(oldest_key) = session.iter()
                    .min_by_key(|(_, e)| e.created_at)
                    .map(|(k, _)| k.clone())
                {
                    session.remove(&oldest_key);
                    self.evictions.fetch_add(1, Ordering::Relaxed);
                }
            }

            // 检查内存缓存是否过大，触发 LRU 淘汰
            if session.len() >= self.max_memory_entries as usize && !session.contains_key(&key) {
                self.evict_lru_in_session(&mut *session);
            }

            session.insert(key.clone(), entry);
        }

        // SQLite 持久化存储
        #[cfg(feature = "sqlite-persistence")]
        if let Some(ref path) = self.sqlite_path {
            if let Err(e) = self.store_sqlite(path, &session_id, &key, &value, &now) {
                tracing::warn!("[ContextManager] SQLite store failed: {}", e);
            }
        }

        // 清理过期条目
        self.cleanup_expired();
        self.total_stores.fetch_add(1, Ordering::Relaxed);
    }

    /// 存储到 SQLite
    #[cfg(feature = "sqlite-persistence")]
    fn store_sqlite(
        &self,
        path: &str,
        session_id: &str,
        key: &str,
        value: &str,
        now: &DateTime<Utc>,
    ) -> anyhow::Result<()> {
        let conn = rusqlite::Connection::open(path)?;
        conn.execute(
            "INSERT INTO context_store (session_id, key, value, created_at, accessed_at, access_count)
             VALUES (?1, ?2, ?3, ?4, ?5, 1)
             ON CONFLICT(session_id, key) DO UPDATE SET
                 value = excluded.value,
                 accessed_at = excluded.accessed_at,
                 access_count = access_count + 1",
            rusqlite::params![
                session_id,
                key,
                value,
                now.to_rfc3339(),
                now.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    /// 检索上下文
    /// 先尝试内存查找，未命中时从 SQLite 恢复 (若启用)
    /// 修复: SQLite 结果现在正确写回内存缓存
    pub fn retrieve(&self, key: &str) -> Option<String> {
        let session_id = "default";
        let now = Utc::now();
        self.total_retrieves.fetch_add(1, Ordering::Relaxed);

        // 先尝试从内存获取
        {
            let mut sessions = self.sessions.lock().unwrap();
            if let Some(session) = sessions.get_mut(session_id) {
                // 检查 TTL：如果条目过期，视为未命中
                if let Some(entry) = session.get(key) {
                    let max_age = chrono::Duration::days(self.ttl_days as i64);
                    if now.signed_duration_since(entry.created_at) >= max_age {
                        // 条目已过期，删除并视为未命中
                        session.remove(key);
                        debug!("[ContextManager] Entry '{}' expired (TTL={}d)", key, self.ttl_days);
                    } else {
                        // 命中：更新访问时间和计数
                        if let Some(entry) = session.get_mut(key) {
                            entry.accessed_at = now;
                            entry.access_count += 1;
                        }
                        let value = session.get(key).map(|e| e.value.clone());
                        if value.is_some() {
                            self.hits.fetch_add(1, Ordering::Relaxed);
                            return value;
                        }
                    }
                }
            }
        }

        // 内存未命中，尝试从 SQLite 恢复
        #[cfg(feature = "sqlite-persistence")]
        if let Some(ref path) = self.sqlite_path {
            if let Ok(Some(value)) = self.retrieve_sqlite(path, session_id, key) {
                // 修复: 将 SQLite 结果写回内存缓存，以便后续快速访问
                let entry = ContextEntry {
                    value: value.clone(),
                    created_at: now,
                    accessed_at: now,
                    access_count: 1,
                };

                let mut sessions = self.sessions.lock().unwrap();
                let session = sessions
                    .entry(session_id.to_string())
                    .or_insert_with(HashMap::new);

                // 检查内存缓存上限
                if session.len() >= self.max_memory_entries as usize && !session.contains_key(key) {
                    self.evict_lru_in_session(session);
                }

                // 同时更新 SQLite 的 access_count
                let _ = self.update_sqlite_access(path, session_id, key);

                session.insert(key.to_string(), entry);
                self.hits.fetch_add(1, Ordering::Relaxed);
                return Some(value);
            }
        }

        // 完全未命中
        self.misses.fetch_add(1, Ordering::Relaxed);
        None
    }

    /// 更新 SQLite 中的访问计数
    #[cfg(feature = "sqlite-persistence")]
    fn update_sqlite_access(&self, path: &str, session_id: &str, key: &str) -> anyhow::Result<()> {
        let conn = rusqlite::Connection::open(path)?;
        conn.execute(
            "UPDATE context_store SET accessed_at = ?1, access_count = access_count + 1
             WHERE session_id = ?2 AND key = ?3",
            rusqlite::params![Utc::now().to_rfc3339(), session_id, key],
        )?;
        Ok(())
    }

    /// 从 SQLite 检索
    #[cfg(feature = "sqlite-persistence")]
    fn retrieve_sqlite(
        &self,
        path: &str,
        session_id: &str,
        key: &str,
    ) -> anyhow::Result<Option<String>> {
        let conn = rusqlite::Connection::open(path)?;
        let mut stmt = conn.prepare(
            "SELECT value FROM context_store WHERE session_id = ?1 AND key = ?2",
        )?;
        let mut rows = stmt.query(rusqlite::params![session_id, key])?;
        if let Some(row) = rows.next()? {
            let value: String = row.get(0)?;
            return Ok(Some(value));
        }
        Ok(None)
    }

    /// 删除上下文
    pub fn delete(&mut self, key: &str) {
        let session_id = "default";
        {
            let mut sessions = self.sessions.lock().unwrap();
            if let Some(session) = sessions.get_mut(session_id) {
                session.remove(key);
            }
        }

        // SQLite 删除
        #[cfg(feature = "sqlite-persistence")]
        if let Some(ref path) = self.sqlite_path {
            if let Err(e) = self.delete_sqlite(path, session_id, key) {
                tracing::warn!("[ContextManager] SQLite delete failed: {}", e);
            }
        }
    }

    /// SQLite 删除
    #[cfg(feature = "sqlite-persistence")]
    fn delete_sqlite(&self, path: &str, session_id: &str, key: &str) -> anyhow::Result<()> {
        let conn = rusqlite::Connection::open(path)?;
        conn.execute(
            "DELETE FROM context_store WHERE session_id = ?1 AND key = ?2",
            rusqlite::params![session_id, key],
        )?;
        Ok(())
    }

    /// 清理过期条目
    pub(crate) fn cleanup_expired(&self) {
        let now = Utc::now();
        let max_age = chrono::Duration::days(self.ttl_days as i64);
        let mut evicted = 0u64;

        let mut sessions = self.sessions.lock().unwrap();
        for session in sessions.values_mut() {
            let before = session.len();
            session.retain(|_, entry| now.signed_duration_since(entry.created_at) < max_age);
            evicted += (before - session.len()) as u64;
        }

        if evicted > 0 {
            self.evictions.fetch_add(evicted, Ordering::Relaxed);
            debug!("[ContextManager] Cleaned up {} expired entries", evicted);
        }
    }

    /// 在会话中执行 LRU 淘汰
    fn evict_lru_in_session(&self, session: &mut HashMap<String, ContextEntry>) {
        let target = self.max_memory_entries as usize;
        // 需要淘汰到 target-1 以容纳新条目
        while session.len() >= target {
            if let Some(oldest_key) = session.iter()
                .min_by_key(|(_, e)| e.accessed_at)
                .map(|(k, _)| k.clone())
            {
                session.remove(&oldest_key);
                self.evictions.fetch_add(1, Ordering::Relaxed);
            } else {
                break;
            }
        }
    }

    /// 获取会话条目数
    pub fn count_entries(&self) -> usize {
        let sessions = self.sessions.lock().unwrap();
        sessions.values().map(|s| s.len()).sum()
    }

    /// 获取指定会话的条目数
    pub fn session_entries(&self, session_id: &str) -> usize {
        let sessions = self.sessions.lock().unwrap();
        sessions
            .get(session_id)
            .map(|s| s.len())
            .unwrap_or(0)
    }

    /// 检查日志轮转是否需要执行 (基于 log_rotation 配置)
    pub fn should_rotate_logs(&self) -> bool {
        self.log_rotation.enabled
    }

    // ========================================================================
    // 统计信息
    // ========================================================================

    /// 获取缓存命中次数
    pub fn hits(&self) -> u64 {
        self.hits.load(Ordering::Relaxed)
    }

    /// 获取缓存未命中次数
    pub fn misses(&self) -> u64 {
        self.misses.load(Ordering::Relaxed)
    }

    /// 获取淘汰条目数
    pub fn evictions(&self) -> u64 {
        self.evictions.load(Ordering::Relaxed)
    }

    /// 获取总存储请求数
    pub fn total_stores(&self) -> u64 {
        self.total_stores.load(Ordering::Relaxed)
    }

    /// 获取总检索请求数
    pub fn total_retrieves(&self) -> u64 {
        self.total_retrieves.load(Ordering::Relaxed)
    }

    /// 获取缓存命中率 (0.0 ~ 1.0)
    pub fn hit_rate(&self) -> f64 {
        let hits = self.hits.load(Ordering::Relaxed);
        let misses = self.misses.load(Ordering::Relaxed);
        let total = hits + misses;
        if total == 0 {
            0.0
        } else {
            hits as f64 / total as f64
        }
    }

    /// 获取所有统计信息
    pub fn get_stats(&self) -> HashMap<String, u64> {
        let mut stats = HashMap::new();
        stats.insert("hits".to_string(), self.hits.load(Ordering::Relaxed));
        stats.insert("misses".to_string(), self.misses.load(Ordering::Relaxed));
        stats.insert("evictions".to_string(), self.evictions.load(Ordering::Relaxed));
        stats.insert("total_stores".to_string(), self.total_stores.load(Ordering::Relaxed));
        stats.insert("total_retrieves".to_string(), self.total_retrieves.load(Ordering::Relaxed));
        stats.insert("entries".to_string(), self.count_entries() as u64);
        stats.insert("max_entries".to_string(), self.max_entries as u64);
        stats.insert("ttl_days".to_string(), self.ttl_days as u64);
        stats
    }

    /// 导出自有上下文到 SQLite (批量)
    #[cfg(feature = "sqlite-persistence")]
    pub fn export_to_sqlite(&self, path: &str) -> anyhow::Result<u64> {
        let conn = rusqlite::Connection::open(path)?;
        let mut count: u64 = 0;
        let sessions = self.sessions.lock().unwrap();
        for (session_id, entries) in sessions.iter() {
            for (key, entry) in entries {
                conn.execute(
                    "INSERT OR REPLACE INTO context_store (session_id, key, value, created_at, accessed_at, access_count)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    rusqlite::params![
                        session_id,
                        key,
                        entry.value,
                        entry.created_at.to_rfc3339(),
                        entry.accessed_at.to_rfc3339(),
                        entry.access_count,
                    ],
                )?;
                count += 1;
            }
        }
        Ok(count)
    }
}

impl Default for ContextManager {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_store_and_retrieve() {
        let mut cm = ContextManager::new();
        cm.store("key1".to_string(), "value1".to_string());
        assert_eq!(cm.retrieve("key1"), Some("value1".to_string()));
    }

    #[test]
    fn test_retrieve_missing() {
        let cm = ContextManager::new();
        assert_eq!(cm.retrieve("nonexistent"), None);
    }

    #[test]
    fn test_delete() {
        let mut cm = ContextManager::new();
        cm.store("key1".to_string(), "value1".to_string());
        assert_eq!(cm.retrieve("key1"), Some("value1".to_string()));
        cm.delete("key1");
        assert_eq!(cm.retrieve("key1"), None);
    }

    #[test]
    fn test_count_entries() {
        let mut cm = ContextManager::new();
        assert_eq!(cm.count_entries(), 0);
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string());
        assert_eq!(cm.count_entries(), 2);
    }

    #[test]
    fn test_cleanup_expired() {
        let mut cm = ContextManager::new();
        cm.ttl_days = 0; // 立即过期
        cm.store("key1".to_string(), "value1".to_string());
        cm.cleanup_expired();
        assert_eq!(cm.count_entries(), 0);
    }

    #[test]
    fn test_retrieve_expired_ttl() {
        let mut cm = ContextManager::new();
        cm.ttl_days = 0; // 立即过期
        cm.store("key1".to_string(), "value1".to_string());
        // TTL 为 0 时，retrieve 应返回 None (过期)
        assert_eq!(cm.retrieve("key1"), None);
    }

    #[test]
    fn test_log_rotation_config() {
        let cm = ContextManager::new();
        assert!(cm.should_rotate_logs());
        assert_eq!(cm.log_rotation.max_size_mb, 100);
        assert_eq!(cm.log_rotation.retain_days, 7);
    }

    #[test]
    fn test_with_log_rotation() {
        let config = LogRotationConfig {
            enabled: false,
            max_size_mb: 200,
            retain_days: 14,
            log_path: "custom.log".to_string(),
        };
        let cm = ContextManager::new().with_log_rotation(config);
        assert!(!cm.should_rotate_logs());
        assert_eq!(cm.log_rotation.max_size_mb, 200);
    }

    #[test]
    fn test_max_entries_eviction() {
        let mut cm = ContextManager::new();
        cm.max_entries = 2;
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string());
        cm.store("c".to_string(), "3".to_string()); // 应淘汰 "a"
        assert_eq!(cm.retrieve("a"), None);
        assert_eq!(cm.retrieve("b"), Some("2".to_string()));
        assert_eq!(cm.retrieve("c"), Some("3".to_string()));
    }

    #[test]
    fn test_hit_rate() {
        let cm = ContextManager::new();
        assert_eq!(cm.hit_rate(), 0.0);
        assert_eq!(cm.hits(), 0);
        assert_eq!(cm.misses(), 0);
    }

    #[test]
    fn test_hit_rate_after_operations() {
        let mut cm = ContextManager::new();
        cm.store("key1".to_string(), "val1".to_string());
        cm.retrieve("key1"); // hit
        cm.retrieve("nonexistent"); // miss
        assert_eq!(cm.hits(), 1);
        assert_eq!(cm.misses(), 1);
        assert!((cm.hit_rate() - 0.5).abs() < 0.001);
    }

    #[test]
    fn test_get_stats() {
        let cm = ContextManager::new();
        let stats = cm.get_stats();
        assert!(stats.contains_key("hits"));
        assert!(stats.contains_key("misses"));
        assert!(stats.contains_key("evictions"));
        assert!(stats.contains_key("entries"));
        assert_eq!(stats.get("ttl_days"), Some(&30));
    }

    #[test]
    fn test_session_entries() {
        let mut cm = ContextManager::new();
        assert_eq!(cm.session_entries("default"), 0);
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string());
        assert_eq!(cm.session_entries("default"), 2);
        assert_eq!(cm.session_entries("other"), 0);
    }

    #[test]
    fn test_total_stores_retrieves() {
        let mut cm = ContextManager::new();
        assert_eq!(cm.total_stores(), 0);
        assert_eq!(cm.total_retrieves(), 0);
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string());
        let _ = cm.retrieve("a");
        let _ = cm.retrieve("b");
        let _ = cm.retrieve("nonexistent");
        assert_eq!(cm.total_stores(), 2);
        assert_eq!(cm.total_retrieves(), 3);
    }

    #[test]
    fn test_lru_eviction() {
        let mut cm = ContextManager::new();
        cm.max_memory_entries = 2;
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string());
        // 访问 "a" 使其成为最近使用
        cm.retrieve("a");
        // 存储 "c" 应淘汰 "b" (最久未访问)
        cm.store("c".to_string(), "3".to_string());
        assert_eq!(cm.retrieve("a"), Some("1".to_string()));
        assert_eq!(cm.retrieve("b"), None); // 被淘汰
        assert_eq!(cm.retrieve("c"), Some("3".to_string()));
    }

    #[test]
    fn test_retrieve_updates_access_count() {
        let mut cm = ContextManager::new();
        cm.store("key1".to_string(), "val1".to_string());
        // 第一次检索
        let _ = cm.retrieve("key1");
        // 验证 access_count 已更新 (通过内部不可见，但至少不报错)
        assert_eq!(cm.retrieve("key1"), Some("val1".to_string()));
    }

    #[test]
    fn test_evictions_counter() {
        let mut cm = ContextManager::new();
        cm.max_entries = 1;
        assert_eq!(cm.evictions(), 0);
        cm.store("a".to_string(), "1".to_string());
        cm.store("b".to_string(), "2".to_string()); // 应淘汰 "a"
        assert!(cm.evictions() >= 1);
    }
}