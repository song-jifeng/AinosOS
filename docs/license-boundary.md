# Ainos OS 许可证边界说明

## 概览

Ainos OS 项目采用**双许可证**策略：

- **GPL-2.0** — 内核模块及与 Linux 内核紧密耦合的代码
- **MIT** — 用户空间守护进程、SDK、运行时、工具、文档

## GPL 目录（Linux 内核模块）

以下目录中的所有代码使用 **GPL-2.0** 许可证：

| 目录 | 说明 | 许可证 |
|------|------|--------|
| `kernel/` | Linux 内核模块（调度器、系统调用、procfs 等） | GPL-2.0 |
| `kernel/ai-proc/` | /proc/ai 虚拟文件系统和桥接器 | GPL-2.0 |
| `kernel/ai-self-heal/` | 内核自愈模块 | GPL-2.0 |
| `kernel/ai-kill/` | AI KILL 进程管理器 | GPL-2.0 |
| `kernel/ai-tmpfs/` | AI tmpfs 智能文件系统 | GPL-2.0 |
| `kernel/ai-readahead/` | AI readahead 智能预读 | GPL-2.0 |
| `kernel/hotpatch/` | 热补丁生成器 | GPL-2.0 |
| `kernel/include/` | 内核头文件 | GPL-2.0 |
| `ai-fs/` | AI 文件系统（FUSE 内核侧交互） | GPL-2.0 |
| `ai-policy/` | AI 安全策略（内核策略执行） | GPL-2.0 |

## MIT 目录（用户空间）

以下目录中的所有代码使用 **MIT** 许可证：

| 目录 | 说明 |
|------|------|
| `system-services/` | 系统服务层（守护进程等） |
| `ai-runtime/` | AI 运行时层 |
| `userland/` | 用户空间 SDK |
| `configs/` | 配置文件 |
| `scripts/` | 脚本工具 |
| `docs/` | 文档 |
| `models/` | 模型文件目录 |
| `data/` | 数据存储目录 |
| `logs/` | 日志目录 |
| `weelink-agent/` | 多智能体协作系统 |
| `tools/` | 开发工具（如果存在） |

## 根目录文件

| 文件 | 许可证 |
|------|--------|
| `LICENSE` | MIT（项目默认许可证） |
| `README.md` | MIT |
| 各子目录下的 `COPYING` 文件 | GPL-2.0（仅 GPL 目录） |

## GPL 传染性边界说明

### 什么是传染性

GPL-2.0 的"传染性"是指：如果一个程序包含了 GPL 代码，那么整个程序必须也以 GPL 发布。

### 边界规则

1. **内核模块**：所有直接编译进 Linux 内核模块（`.ko`）的代码必须为 GPL-2.0。这些代码通过 Linux 内核头文件（`<linux/module.h>` 等）与内核交互，受 GPL 传染。

2. **系统调用接口**：用户空间程序通过系统调用（`ioctl`、`sysfs`、`procfs`）与内核模块通信，不受 GPL 传染性限制。这是 Linux 内核社区公认的"系统调用例外"（System Call Exception）。

3. **IPC 通信**：用户空间守护进程通过 TCP/Unix Domain Socket 与内核桥接器通信，不受 GPL 传染性限制。

4. **FUSE 文件系统**：`ai-fs/` 目录中的代码通过 FUSE 接口与内核交互。FUSE 库本身是 LGPL，但 ai-fs 直接与内核 VFS 交互，因此使用 GPL-2.0。用户空间程序通过 FUSE 挂载点访问文件，不受 GPL 传染。

5. **动态链接**：`libainos`（C SDK）通过标准 IPC 与 daemon 通信，不直接链接任何 GPL 代码，因此保持 MIT。

### 违反边界的常见错误

| 错误做法 | 后果 |
|----------|------|
| 在 MIT 代码中 `#include <linux/module.h>` 或其它内核头文件 | 自动触发 GPL 传染 |
| 在 MIT 代码中直接链接（静态或动态）GPL 库 | 整个程序必须改为 GPL |
| 在 MIT 代码中复制 GPL 代码片段 | 整个文件必须改为 GPL |

### 文件头部标记

所有 GPL 文件必须在文件顶部包含明确的 SPDX 标识：

```c
// SPDX-License-Identifier: GPL-2.0
```

所有 MIT 文件应在文件顶部包含：

```c
// SPDX-License-Identifier: MIT
```

未标记许可证的文件默认采用项目根目录 `LICENSE` 文件中的 MIT 许可证。

## 新增文件时的许可证选择

1. 如果文件位于 `kernel/`、`ai-fs/`、`ai-policy/` 目录下，**必须**使用 GPL-2.0
2. 如果文件位于其他目录，默认使用 MIT
3. 如果文件需要同时在内核和用户空间使用（如公共头文件），使用 `#ifdef __KERNEL__` 隔离 GPL 部分，并在头部说明

## 参考

- [GNU GPL v2.0 全文](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
- [MIT 许可证全文](https://opensource.org/licenses/MIT)
- [Linux 内核 COPYING 文件](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/COPYING)