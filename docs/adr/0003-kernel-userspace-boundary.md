# ADR-0003: 内核模块仅限 Linux，用户空间跨平台

## 状态
Accepted

## 日期
2026-08-02

## 背景
Ainos OS 的 AI 调度器、AI 文件系统、AI 安全策略等模块最初设计为 Linux 内核模块。
但项目需要支持 Windows 双平台。

## 决策
- Linux 内核模块（AI 调度器、ai-fs、ai-policy）仅限 Linux
- 用户空间组件（AI 守护进程、Runtime、SDK）跨平台
- Windows 上使用用户态等效方案替代内核模块功能
- 内核模块代码使用 GPL 许可证，与用户空间 MIT 明确分离

## 影响
- 正面：内核模块可充分利用 Linux 内核机制
- 正面：用户空间代码不受 GPL 传染
- 负面：Windows 上缺少内核级 AI 调度器
- 负面：需要维护两套构建系统

## 许可证边界
```
kernel/          → GPL-2.0 (Linux 内核)
ai-fs/           → GPL-2.0 (FUSE 内核模块或用户态 FUSE)
ai-policy/       → GPL-2.0 (LSM 模块)
其余所有代码     → MIT
```