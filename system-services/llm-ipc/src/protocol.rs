// LLM-as-IPC 协议定义

use serde::{Deserialize, Serialize};

/// IPC 协议版本
pub const PROTOCOL_VERSION: &str = "1.0.0";

/// 消息类型
#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum MessageType {
    /// 请求
    Request(RequestMessage),
    /// 响应
    Response(ResponseMessage),
    /// 注册
    Register(RegisterMessage),
    /// 心跳
    Heartbeat,
}

/// 请求消息
#[derive(Debug, Serialize, Deserialize)]
pub struct RequestMessage {
    pub id: String,
    pub from: String,
    pub to: String,
    pub message: String,
    pub context: Option<serde_json::Value>,
    pub timeout_ms: Option<u64>,
}

/// 响应消息
#[derive(Debug, Serialize, Deserialize)]
pub struct ResponseMessage {
    pub id: String,
    pub from: String,
    pub to: String,
    pub response: String,
    pub success: bool,
    pub error: Option<String>,
}

/// 注册消息
#[derive(Debug, Serialize, Deserialize)]
pub struct RegisterMessage {
    pub name: String,
    pub description: String,
    pub capabilities: Vec<String>,
}

/// 协议编码解码
pub struct Protocol;

impl Protocol {
    /// 编码消息
    pub fn encode<T: Serialize>(msg: &T) -> anyhow::Result<Vec<u8>> {
        let json = serde_json::to_string(msg)?;
        Ok(json.into_bytes())
    }

    /// 解码消息
    pub fn decode<T: serde::de::DeserializeOwned>(data: &[u8]) -> anyhow::Result<T> {
        let msg = serde_json::from_slice(data)?;
        Ok(msg)
    }

    /// 创建请求
    pub fn create_request(from: &str, to: &str, message: &str) -> MessageType {
        MessageType::Request(RequestMessage {
            id: uuid_v4(),
            from: from.to_string(),
            to: to.to_string(),
            message: message.to_string(),
            context: None,
            timeout_ms: Some(30000),
        })
    }

    /// 创建响应
    pub fn create_response(id: &str, from: &str, to: &str, response: &str) -> MessageType {
        MessageType::Response(ResponseMessage {
            id: id.to_string(),
            from: from.to_string(),
            to: to.to_string(),
            response: response.to_string(),
            success: true,
            error: None,
        })
    }
}

/// 生成简单 UUID
fn uuid_v4() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    format!("msg-{:x}", nanos)
}