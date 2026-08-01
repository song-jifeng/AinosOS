// LLM-as-IPC 桥接器 - 连接现有服务到 LLM IPC

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// 桥接配置
#[derive(Debug, Serialize, Deserialize)]
pub struct BridgeConfig {
    pub service_name: String,
    pub service_description: String,
    pub backend_type: BackendType,
    pub backend_address: String,
}

/// 后端类型
#[derive(Debug, Serialize, Deserialize)]
pub enum BackendType {
    #[serde(rename = "tcp")]
    Tcp,
    #[serde(rename = "unix")]
    Unix,
    #[serde(rename = "http")]
    Http,
    #[serde(rename = "stdin")]
    Stdin,
}

/// 协议转换器
pub struct ProtocolBridge {
    config: BridgeConfig,
    /// 自然语言到命令的映射
    intent_map: HashMap<String, String>,
}

impl ProtocolBridge {
    pub fn new(config: BridgeConfig) -> Self {
        let mut intent_map = HashMap::new();

        // 通用意图映射
        intent_map.insert("hello".to_string(), "status".to_string());
        intent_map.insert("status".to_string(), "status".to_string());
        intent_map.insert("help".to_string(), "help".to_string());
        intent_map.insert("query".to_string(), "query".to_string());
        intent_map.insert("search".to_string(), "search".to_string());
        intent_map.insert("store".to_string(), "store".to_string());
        intent_map.insert("delete".to_string(), "delete".to_string());
        intent_map.insert("update".to_string(), "update".to_string());

        Self {
            config,
            intent_map,
        }
    }

    /// 分析自然语言意图
    pub fn analyze_intent(&self, message: &str) -> Intent {
        let msg_lower = message.to_lowercase();

        if msg_lower.contains("hello") || msg_lower.contains("hi") {
            Intent::Greeting
        } else if msg_lower.contains("status") || msg_lower.contains("health") {
            Intent::Status
        } else if msg_lower.contains("search") || msg_lower.contains("find") || msg_lower.contains("query") {
            Intent::Query
        } else if msg_lower.contains("store") || msg_lower.contains("save") || msg_lower.contains("remember") {
            Intent::Store
        } else if msg_lower.contains("delete") || msg_lower.contains("remove") {
            Intent::Delete
        } else if msg_lower.contains("help") {
            Intent::Help
        } else {
            Intent::Unknown
        }
    }

    /// 将自然语言转换为后端命令
    pub fn translate(&self, message: &str) -> String {
        let intent = self.analyze_intent(message);

        match intent {
            Intent::Greeting => format!("GREET {}", self.config.service_name),
            Intent::Status => format!("STATUS {}", self.config.service_name),
            Intent::Query => format!("QUERY {}", message),
            Intent::Store => format!("STORE {}", message),
            Intent::Delete => format!("DELETE {}", message),
            Intent::Help => format!("HELP {}", self.config.service_name),
            Intent::Unknown => format!("PROCESS {}", message),
        }
    }

    /// 将后端响应转换为自然语言
    pub fn translate_response(&self, response: &str, intent: &Intent) -> String {
        match intent {
            Intent::Greeting => {
                format!("Hello! I am the {} service. How can I assist you?", self.config.service_name)
            }
            Intent::Status => {
                format!("{} status: {}", self.config.service_name, response)
            }
            _ => {
                format!("[{}] {}", self.config.service_name, response)
            }
        }
    }
}

/// 意图
#[derive(Debug, PartialEq)]
pub enum Intent {
    Greeting,
    Status,
    Query,
    Store,
    Delete,
    Help,
    Unknown,
}