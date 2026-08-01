// Ainos AI Daemon - Context Manager

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

/// 上下文管理器 - 会话级记忆存储
#[derive(Debug)]
pub struct ContextManager {
    /// 上下文存储 (session_id -> (key -> entry))
    sessions: HashMap<String, HashMap<String, ContextEntry>>,
    /// 最大条目数
    max_entries: u32,
    /// TTL (天)
    ttl_days: u32,
}

impl ContextManager {
    pub fn new() -> Self {
        Self {
            sessions: HashMap::new(),
            max_entries: 10000,
            ttl_days: 30,
        }
    }

    /// 存储上下文
    pub fn store(&mut self, key: String, value: String) {
        let session_id = "default".to_string(); // TODO: 使用真实 session_id
        let now = Utc::now();

        let entry = ContextEntry {
            value,
            created_at: now,
            accessed_at: now,
            access_count: 1,
        };

        let session = self.sessions
            .entry(session_id)
            .or_insert_with(HashMap::new);
        session.insert(key, entry);

        // 清理过期条目
        self.cleanup_expired();
    }

    /// 检索上下文
    pub fn retrieve(&self, key: &str) -> Option<String> {
        let session_id = "default";
        self.sessions
            .get(session_id)
            .and_then(|session| session.get(key))
            .map(|entry| entry.value.clone())
    }

    /// 删除上下文
    pub fn delete(&mut self, key: &str) {
        let session_id = "default";
        if let Some(session) = self.sessions.get_mut(session_id) {
            session.remove(key);
        }
    }

    /// 清理过期条目
    fn cleanup_expired(&mut self) {
        let now = Utc::now();
        let max_age = chrono::Duration::days(self.ttl_days as i64);

        for session in self.sessions.values_mut() {
            session.retain(|_, entry| {
                now.signed_duration_since(entry.created_at) < max_age
            });
        }
    }

    /// 获取会话条目数
    pub fn count_entries(&self) -> usize {
        self.sessions.values()
            .map(|s| s.len())
            .sum()
    }
}