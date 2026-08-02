// Ainos AI Daemon - Context Manager
// 会话级记忆存储，支持 SQLite 持久化 (feature flag: sqlite-persistence)
// 通过 log_rotation 配置管理日志轮转

use std::collections::HashMap;
use chrono::{DateTime, Utc};

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
#[derive(Debug)]
pub struct ContextManager {
    /// 上下文存储 (session_id -> (key -> entry))
    sessions: HashMap<String, HashMap<String, ContextEntry>>,
    /// 最大条目数
    max_entries: u32,
    /// TTL (天)
    ttl_days: u32,
    /// SQLite 持久化路径 (仅当 feature 启用时存在)
    #[cfg(feature = "sqlite-persistence")]
    sqlite_path: Option<String>,
    /// 日志轮转配置
    pub log_rotation: LogRotationConfig,
}

impl ContextManager {
    pub fn new() -> Self {
        Self {
            sessions: HashMap::new(),
            max_entries: 10000,
            ttl_days: 30,
            #[cfg(feature = "sqlite-persistence")]
            sqlite_path: None,
            log_rotation: LogRotationConfig::default(),
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

        // 内存存储
        let session = self
            .sessions
            .entry(session_id.clone())
            .or_insert_with(HashMap::new);

        // 检查是否达到最大条目数，达到则淘汰最旧的
        if session.len() >= self.max_entries as usize && !session.contains_key(&key) {
            if let Some(oldest_key) = session.iter().min_by_key(|(_, e)| e.created_at).map(|(k, _)| k.clone()) {
                session.remove(&oldest_key);
            }
        }

        session.insert(key.clone(), entry);

        // SQLite 持久化存储
        #[cfg(feature = "sqlite-persistence")]
        if let Some(ref path) = self.sqlite_path {
            if let Err(e) = self.store_sqlite(path, &session_id, &key, &value, &now) {
                tracing::warn!("[ContextManager] SQLite store failed: {}", e);
            }
        }

        // 清理过期条目
        self.cleanup_expired();
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
    pub fn retrieve(&self, key: &str) -> Option<String> {
        let session_id = "default";

        // 先尝试从内存获取
        if let Some(entry) = self
            .sessions
            .get(session_id)
            .and_then(|session| session.get(key))
        {
            return Some(entry.value.clone());
        }

        // 内存未命中，尝试从 SQLite 恢复
        #[cfg(feature = "sqlite-persistence")]
        if let Some(ref path) = self.sqlite_path {
            if let Ok(Some(value)) = self.retrieve_sqlite(path, session_id, key) {
                // 恢复到内存以便后续快速访问
                let now = Utc::now();
                let entry = ContextEntry {
                    value: value.clone(),
                    created_at: now,
                    accessed_at: now,
                    access_count: 1,
                };
                // 注意: 这里用了内部可变性的方式，但 sessions 是 &self
                // 为了保持 API 不变，暂不自动恢复回内存，下次 store 会同步
                return Some(value);
            }
        }

        None
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
        if let Some(session) = self.sessions.get_mut(session_id) {
            session.remove(key);
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
    fn cleanup_expired(&mut self) {
        let now = Utc::now();
        let max_age = chrono::Duration::days(self.ttl_days as i64);

        for session in self.sessions.values_mut() {
            session.retain(|_, entry| now.signed_duration_since(entry.created_at) < max_age);
        }
    }

    /// 获取会话条目数
    pub fn count_entries(&self) -> usize {
        self.sessions.values().map(|s| s.len()).sum()
    }

    /// 获取指定会话的条目数
    pub fn session_entries(&self, session_id: &str) -> usize {
        self.sessions
            .get(session_id)
            .map(|s| s.len())
            .unwrap_or(0)
    }

    /// 检查日志轮转是否需要执行 (基于 log_rotation 配置)
    pub fn should_rotate_logs(&self) -> bool {
        self.log_rotation.enabled
    }

    /// 导出自有上下文到 SQLite (批量)
    #[cfg(feature = "sqlite-persistence")]
    pub fn export_to_sqlite(&self, path: &str) -> anyhow::Result<u64> {
        let conn = rusqlite::Connection::open(path)?;
        let mut count: u64 = 0;
        for (session_id, entries) in &self.sessions {
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
}