# ADR-0005: AI 工具包使用 Rust 编写，独立版本管理

## 状态
Accepted

## 日期
2026-08-02

## 背景
ai-tools（ai-git、ai-review 等）是 AI 增强的开发者工具，与操作系统核心组件耦合度低。

## 决策
- ai-tools 使用 Rust 编写，独立 git 仓库
- 通过 Cargo workspace 管理多工具
- 与 ai-daemon 通过标准输入/输出或 HTTP 通信
- 版本独立于主仓库

## 影响
- 正面：独立迭代，不阻塞主项目
- 正面：Rust 生态丰富，适合 CLI 工具
- 负面：需要额外维护 CI 配置
- 负面：用户需要安装 Rust 工具链才能编译

## 已验证
ai-git 已实现语言感知的智能合并引擎和提交信息生成。