// LLM-as-IPC - 进程间自然语言通信
// 进程通过 LLM 用自然语言互相通信

use clap::Parser;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::RwLock;

#[derive(Parser)]
#[command(name = "llm-ipc", version, about = "LLM-powered IPC - process communication via natural language")]
struct Cli {
    /// 监听地址
    #[arg(short, long, default_value = "127.0.0.1:9600")]
    address: String,

    /// 后台运行
    #[arg(short, long)]
    daemon: bool,
}

/// IPC 消息
#[derive(Debug, Serialize, Deserialize, Clone)]
struct IpcMessage {
    from: String,
    to: String,
    message: String,
    context: Option<HashMap<String, String>>,
    timestamp: String,
}

/// 服务注册信息
#[derive(Debug, Clone)]
struct ServiceInfo {
    name: String,
    description: String,
    stream: Option<tokio::sync::mpsc::Sender<String>>,
}

/// IPC 路由器
struct IpcRouter {
    services: HashMap<String, ServiceInfo>,
    message_history: Vec<IpcMessage>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    println!("[llm-ipc] LLM-as-IPC daemon starting...");
    println!("[llm-ipc] Address: {}", cli.address);

    let router = RwLock::new(IpcRouter {
        services: HashMap::new(),
        message_history: Vec::new(),
    });

    // 启动 TCP 监听 (跨平台)
    let listener = TcpListener::bind(&cli.address).await?;
    println!("[llm-ipc] Listening on {}", cli.address);

    let router_ref = std::sync::Arc::new(router);

    // 注册内置服务
    {
        let mut router = router_ref.write().await;
        router.register_builtin_services();
    }
    println!("[llm-ipc] Built-in services registered");

    // 接受连接
    loop {
        let (stream, addr) = match listener.accept().await {
            Ok(conn) => conn,
            Err(e) => {
                eprintln!("[llm-ipc] Accept error: {}", e);
                continue;
            }
        };

        let router = router_ref.clone();
        tokio::spawn(async move {
            if let Err(e) = handle_client(stream, router).await {
                eprintln!("[llm-ipc] Client error: {}", e);
            }
        });
    }
}

impl IpcRouter {
    /// 注册内置服务
    fn register_builtin_services(&mut self) {
        self.services.insert(
            "system".to_string(),
            ServiceInfo {
                name: "system".to_string(),
                description: "System information and status".to_string(),
                stream: None,
            },
        );
        self.services.insert(
            "ai-daemon".to_string(),
            ServiceInfo {
                name: "ai-daemon".to_string(),
                description: "AI inference service".to_string(),
                stream: None,
            },
        );
        self.services.insert(
            "context-mgr".to_string(),
            ServiceInfo {
                name: "context-mgr".to_string(),
                description: "Context management service".to_string(),
                stream: None,
            },
        );
    }

    /// 路由消息
    async fn route_message(&mut self, msg: IpcMessage) -> Option<String> {
        self.message_history.push(msg.clone());

        // 查找目标服务
        if let Some(service) = self.services.get(&msg.to) {
            // 如果有直接连接，转发
            if let Some(tx) = &service.stream {
                let _ = tx.send(msg.message.clone()).await;
                Some(format!("[llm-ipc] Message routed to {}", msg.to))
            } else {
                // 模拟响应
                Some(generate_response(&msg))
            }
        } else {
            // 服务未找到
            Some(format!(
                "[llm-ipc] Service '{}' not found. Available services: {}",
                msg.to,
                self.services.keys().cloned().collect::<Vec<_>>().join(", ")
            ))
        }
    }

    /// 列出服务
    fn list_services(&self) -> String {
        let mut result = String::from("Available services:\n");
        for (name, info) in &self.services {
            result.push_str(&format!("  - {}: {}\n", name, info.description));
        }
        result
    }

    /// 获取历史
    fn get_history(&self, count: usize) -> String {
        let mut result = String::new();
        let start = self.message_history.len().saturating_sub(count);
        for msg in &self.message_history[start..] {
            result.push_str(&format!(
                "[{}] {} -> {}: {}\n",
                msg.timestamp, msg.from, msg.to, msg.message
            ));
        }
        result
    }
}

/// 处理客户端连接
async fn handle_client(
    mut stream: TcpStream,
    router: std::sync::Arc<RwLock<IpcRouter>>,
) -> anyhow::Result<()> {
    let (reader, mut writer) = stream.split();
    let mut buf_reader = BufReader::new(reader);
    let mut line = String::new();

    writer.write_all(b"[llm-ipc] Connected. Use 'help' for commands.\n").await?;

    loop {
        line.clear();
        let n = buf_reader.read_line(&mut line).await?;
        if n == 0 {
            break;
        }

        let line = line.trim();
        let response = match line {
            "help" => {
                "Commands:\n  help             - Show this help\n  list             - List services\n  send <to> <msg>  - Send message\n  history [n]      - Show last n messages\n  register <name>  - Register as service\n  status           - Show router status\n".to_string()
            }
            "list" => {
                let router = router.read().await;
                router.list_services()
            }
            "status" => {
                let router = router.read().await;
                format!(
                    "Services: {}\nMessages: {}\n",
                    router.services.len(),
                    router.message_history.len()
                )
            }
            cmd if cmd.starts_with("send ") => {
                let parts: Vec<&str> = cmd.splitn(3, ' ').collect();
                if parts.len() < 3 {
                    "Usage: send <to> <message>\n".to_string()
                } else {
                    let msg = IpcMessage {
                        from: "client".to_string(),
                        to: parts[1].to_string(),
                        message: parts[2].to_string(),
                        context: None,
                        timestamp: chrono::Local::now().to_rfc3339(),
                    };
                    let mut router = router.write().await;
                    router.route_message(msg).await.unwrap_or_default()
                }
            }
            cmd if cmd.starts_with("history") => {
                let parts: Vec<&str> = cmd.split_whitespace().collect();
                let count = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(10);
                let router = router.read().await;
                router.get_history(count)
            }
            _ => {
                format!("[llm-ipc] Unknown command: {}\nUse 'help' for available commands.\n", line)
            }
        };

        writer.write_all(response.as_bytes()).await?;
        writer.write_all(b"\n").await?;
    }

    Ok(())
}

/// 生成模拟响应
fn generate_response(msg: &IpcMessage) -> String {
    let msg_lower = msg.message.to_lowercase();

    let response = if msg_lower.contains("hello") || msg_lower.contains("hi") {
        format!("Hello from {}! How can I help you?", msg.to)
    } else if msg_lower.contains("status") || msg_lower.contains("how are you") {
        format!("{} is running normally. All systems operational.", msg.to)
    } else if msg_lower.contains("help") || msg_lower.contains("what can you do") {
        format!("{} can: process requests, answer questions, route messages, and more.", msg.to)
    } else {
        format!("[{}] Received: '{}'. Processing your request...", msg.to, msg.message)
    };

    format!(
        "{{\n  \"from\": \"{}\",\n  \"to\": \"{}\",\n  \"response\": \"{}\",\n  \"timestamp\": \"{}\"\n}}",
        msg.to, msg.from, response, chrono::Local::now().to_rfc3339()
    )
}