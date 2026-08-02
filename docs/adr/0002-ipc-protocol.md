# ADR-0002: 使用 TCP JSON 行协议作为跨平台 IPC

## 状态
Accepted

## 日期
2026-08-02

## 背景
AI 守护进程需要与 SDK、用户空间应用通信，且需支持 Windows 和 Linux 双平台。

## 决策
- 使用 TCP 作为主要 IPC 传输层（跨平台）
- Unix Domain Socket 作为 Linux 备选（性能优化）
- 消息格式为 JSON 行协议（每行一个 JSON 对象，以 `\n` 分隔）

## 备选方案
| 方案 | 优势 | 劣势 |
|------|------|------|
| gRPC | 强类型、流式支持 | 依赖重、Windows 编译复杂 |
| Unix Domain Socket 纯方案 | 高性能 | Windows 不支持 |
| HTTP REST | 调试方便 | 额外 HTTP 解析开销 |

## 影响
- 正面：TCP 实现简单，跨平台一致
- 正面：JSON 行协议调试方便，可读性强
- 负面：缺少 TLS 加密（见 ADR-0003）
- 负面：JSON 解析性能不如二进制协议

## 未来改进
- 在 TCP 之上添加 TLS 支持（ADR-0003）
- 可考虑对高吞吐场景使用 MessagePack 替代 JSON