# AinosOS 入门指南 / Getting Started Guide

> **AinosOS — AI 原生操作系统 / AI-Native Operating System**
>
> 本指南将帮助你在各种平台上快速安装、配置和运行 AinosOS AI 守护进程，并完成你的第一次 AI 推理。
>
> This guide helps you quickly install, configure, and run the AinosOS AI Daemon on various platforms, and perform your first AI inference.

---

## 目录 / Table of Contents

1. [5 分钟快速上手 / 5-Minute Quick Start](#1-5-分钟快速上手--5-minute-quick-start)
2. [全平台安装 / Installation on All Platforms](#2-全平台安装--installation-on-all-platforms)
3. [配置 / Configuration](#3-配置--configuration)
4. [首次推理 / First Inference](#4-首次推理--first-inference)
5. [模型管理 / Model Management](#5-模型管理--model-management)
6. [故障排除 / Troubleshooting](#6-故障排除--troubleshooting)

---

## 1. 5 分钟快速上手 / 5-Minute Quick Start

### 1.1 Windows

#### 一键安装 / One-Click Installation

打开 **命令提示符（管理员）** / Open **Command Prompt (Admin)**:

```batch
cd D:\Ainos
scripts\install.bat
```

安装脚本会自动执行以下步骤 / The install script performs the following steps:

1. **检查 Rust 工具链** / Check Rust toolchain — 如果未安装，请先访问 https://rustup.rs 安装
2. **创建目录结构** / Create directory structure — `models/`, `data/contexts/`, `logs/`
3. **编译 AI 守护进程** / Build the AI daemon — `cargo build --release`
4. **注册 Windows 服务（可选）** / Register Windows service (optional) — 创建 `AinosDaemon` 服务
5. **显示安装完成信息** / Show installation summary

#### 手动启动 / Manual Start

```batch
cd D:\Ainos\system-services\ai-daemon
target\release\ai-daemon.exe -c ..\..\configs\ai-daemon.toml -v
```

#### 启动系统托盘 / Start System Tray

```batch
python scripts\ainos_tray.py
```

系统托盘提供以下功能 / The system tray provides:

- 守护进程状态指示器 / Daemon status indicator
- 启动/停止守护进程 / Start/Stop daemon
- 打开 Web 管理面板 / Open web panel
- 查看日志 / View logs
- 退出 / Exit

#### 验证安装 / Verify Installation

```batch
python scripts\verification_test.py
```

验收测试会执行 6 项 IPC 操作验证 / The verification test executes 6 IPC operations:

- 系统状态查询 / System Status
- 云端推理请求 / Cloud Inference
- 上下文存储 / Context Store
- 上下文检索 / Context Retrieve
- 模型列表查询 / Model List
- 温控策略状态 / Thermal Status

#### 访问 Web 面板 / Access Web Panel

```batch
python system-services\web-panel\web_server.py
```

打开浏览器访问 / Open browser to: http://127.0.0.1:9501

Web 面板提供 / The web panel provides:

- 系统状态仪表盘 / System status dashboard
- 推理测试界面 / Inference test interface
- 模型管理 / Model management
- 上下文查看 / Context viewer
- 日志查看 / Log viewer

---

### 1.2 Linux

#### 一键安装 / One-Click Installation

```bash
cd /path/to/Ainos
bash scripts/install.sh
```

安装脚本会自动执行以下步骤 / The install script performs the following steps:

1. **检查依赖** / Check dependencies — Rust, CMake, Python
2. **创建目录结构** / Create directory structure — `models/`, `data/contexts/`, `logs/`
3. **编译守护进程** / Build the daemon — `cargo build --release`
4. **安装 systemd 服务** / Install systemd service
5. **显示安装完成信息** / Show installation summary

#### 手动启动 / Manual Start

```bash
cd system-services/ai-daemon
./target/release/ai-daemon -c ../../configs/ai-daemon.toml -v
```

#### 使用 systemd 服务 / Using systemd Service

```bash
# 启动服务 / Start service
sudo systemctl start ai-daemon

# 设置开机自启 / Enable on boot
sudo systemctl enable ai-daemon

# 查看状态 / Check status
sudo systemctl status ai-daemon

# 查看日志 / View logs
sudo journalctl -u ai-daemon -f

# 停止服务 / Stop service
sudo systemctl stop ai-daemon
```

#### 验证安装 / Verify Installation

```bash
python3 scripts/verification_test.py
```

---

### 1.3 Docker

#### 使用 Docker Compose / Using Docker Compose

```bash
cd /path/to/Ainos
docker-compose up -d
```

这会启动三个服务 / This starts three services:

- **ai-daemon**: 核心 AI 守护进程 / Core AI daemon service
- **web-panel**: Web 管理面板（可选，通过 `--profile web` 启用） / Web management panel (optional, enable with `--profile web`)
- **redis-cache**: Redis 缓存（可选，通过 `--profile cache` 启用） / Redis cache (optional, enable with `--profile cache`)

#### 使用特定配置文件 / Using Specific Profiles

```bash
# 仅启动核心守护进程 / Core daemon only
docker-compose up -d ai-daemon

# 启动完整堆栈 / Full stack with web and cache
docker-compose --profile full up -d
```

#### 查看日志 / View Logs

```bash
docker-compose logs -f ai-daemon
```

#### 验证安装 / Verify Installation

```bash
# 健康检查 / Health check
docker ps | grep ainos-daemon

# 查看健康状态 / Check health status
docker inspect --format='{{.State.Health.Status}}' ainos-daemon
```

---

### 1.4 macOS

#### 使用 launchd / Using launchd

```bash
# 安装 launchd 服务 / Install launchd service
sudo cp platform/darwin/com.ainos.daemon.plist /Library/LaunchDaemons/

# 加载服务 / Load service
sudo launchctl load /Library/LaunchDaemons/com.ainos.daemon.plist

# 启动服务 / Start service
sudo launchctl start com.ainos.daemon
```

#### 手动启动 / Manual Start

```bash
cd system-services/ai-daemon
./target/release/ai-daemon -c ../../configs/ai-daemon.toml -v
```

#### 验证安装 / Verify Installation

```bash
# 检查服务状态 / Check service status
sudo launchctl list | grep ainos

# 运行验收测试 / Run verification test
python3 scripts/verification_test.py
```

---

### 1.5 验证测试详解 / Verification Test Details

验收测试脚本 (`scripts/verification_test.py`) 通过 TCP IPC 连接守护进程，执行 6 项全链路测试：

The verification test script connects to the daemon via TCP IPC and executes 6 end-to-end tests:

```python
# 测试 1: 系统状态查询 / System Status
resp = send_request("Status")
# 验证: type == "StatusResponse", 包含 uptime, models_loaded 等字段

# 测试 2: 云端推理请求 / Cloud Inference
resp = send_request("Inference", {
    "model": "default",
    "prompt": "请用中文介绍Ainos OS是什么？",
    "temperature": 0.7,
    "max_tokens": 200
})
# 验证: type == "InferenceResponse", output 长度 > 20 字

# 测试 3: 上下文存储 / Context Store
resp = send_request("ContextStore", {
    "key": "test-session-001",
    "value": "用户偏好: 中文, 技术话题, 离线优先"
})
# 验证: type == "InferenceResponse"

# 测试 4: 上下文检索 / Context Retrieve
resp = send_request("ContextRetrieve", {
    "key": "test-session-001"
})
# 验证: 检索到存储的内容

# 测试 5: 模型列表查询 / Model List
resp = send_request("ModelList")
# 验证: type == "ModelListResponse", 包含 models 数组

# 测试 6: 温控策略状态 / Thermal Status
# 连续查询 3 次 Status 验证守护进程持续响应
```

运行结果示例 / Example output:

```
[AINOS] Ainos OS 全链路验收测试
   目标: 127.0.0.1:9500
   时间: 2024-01-01 12:00:00

============================================================
[1/6] 系统状态查询 (Status)
============================================================
  [PASS] 运行时间: 3600s, 模型: 1, 请求: 42, 网络: 可用

============================================================
[2/6] 云端推理请求 (Inference)
============================================================
  [PASS] 输出长度: 156字, 来源: cloud, 耗时: 2340ms

...

[验收汇总]
  [PASS] Status
  [PASS] Inference
  [PASS] ContextStore
  [PASS] ContextRetrieve
  [PASS] ModelList
  [PASS] Thermal

  结果: 6/6 通过
  [ALL PASS] 全部通过！
```

---

## 2. 全平台安装 / Installation on All Platforms

### 2.1 Windows

#### 前提条件 / Prerequisites

| 软件 / Software | 版本 / Version | 说明 / Description |
|----------------|---------------|-------------------|
| Rust | 1.77+ | 通过 rustup.rs 安装 |
| Python | 3.8+ | 从 python.org 下载 |
| Git | 任意版本 | 从 git-scm.com 下载 |
| Visual Studio Build Tools | 2022+ | 可选，用于 C++ 编译 |

#### 从源码构建 / Build from Source

```batch
REM 1. 克隆仓库 / Clone repository
git clone https://github.com/ainos-os/ainos.git
cd ainos

REM 2. 创建必要目录 / Create required directories
mkdir models data\contexts logs

REM 3. 编译 AI 守护进程 / Build AI daemon
cd system-services\ai-daemon
cargo build --release

REM 4. 复制配置文件 / Copy configuration
copy ..\..\configs\ai-daemon.toml .

REM 5. 运行守护进程 / Run daemon
target\release\ai-daemon.exe -c ..\..\configs\ai-daemon.toml -v
```

#### 构建特定功能 / Build with Specific Features

```batch
REM 基础构建 / Basic build
cargo build --release

REM 启用 SQLite 持久化 / Enable SQLite persistence
cargo build --release --features sqlite-persistence

REM 启用 TLS 加密 / Enable TLS
cargo build --release --features tls

REM 启用完整功能 / Enable all features
cargo build --release --features full
```

#### Windows 服务模式 / Windows Service Mode

```batch
REM 安装服务 / Install service
sc create AinosDaemon binPath= "D:\Ainos\system-services\ai-daemon\target\release\ai-daemon.exe -c D:\Ainos\configs\ai-daemon.toml -v" start= auto

REM 启动服务 / Start service
sc start AinosDaemon

REM 停止服务 / Stop service
sc stop AinosDaemon

REM 卸载服务 / Uninstall service
sc delete AinosDaemon
```

#### 系统托盘集成 / System Tray Integration

```batch
REM 启动系统托盘 / Start system tray
python scripts\ainos_tray.py

REM 注册开机自启 / Register auto-start
python scripts\register_autostart.py
```

`scripts/register_autostart.py` 支持 / supports:

- Windows: 注册表 Run 键 / Registry Run key
- Linux: autostart .desktop 文件 / autostart .desktop file
- macOS: LaunchAgents plist 文件 / LaunchAgents plist file

#### 命名管道 IPC / Named Pipe IPC

在 Windows 上，守护进程通过 TCP (`127.0.0.1:9500`) 进行 IPC 通信。命名管道支持通过 `winapi` crate 实现，包含以下功能：

On Windows, the daemon communicates via TCP (`127.0.0.1:9500`). Named pipe support is implemented via the `winapi` crate, including:

- 命名管道创建 / Named pipe creation
- 访问控制列表 / Access control lists (ACL)
- 安全描述符 / Security descriptors
- 异步 I/O / Asynchronous I/O

相关依赖 / Related dependencies (Cargo.toml):

```toml
[target.'cfg(windows)'.dependencies]
winapi = { version = "0.3", features = [
    "winbase", "winnt", "handleapi", "synchapi",
    "ioapiset", "errhandlingapi", "minwinbase",
    "securitybaseapi", "accctrl", "aclapi",
    "fileapi", "namedpipeapi", "processthreadsapi",
    "winreg", "winuser", "winsvc", "evntprov",
    "evntrace", "shellapi", "psapi", "tlhelp32",
    "strsafe", "combaseapi",
] }
```

#### 防火墙配置 / Firewall Configuration

如果防火墙阻止守护进程，请添加入站规则：

If the firewall blocks the daemon, add an inbound rule:

```batch
netsh advfirewall firewall add rule name="Ainos AI Daemon" dir=in action=allow protocol=TCP localport=9500
```

#### 杀毒软件排除 / Antivirus Exclusion

建议将以下目录添加到杀毒软件排除列表：

It is recommended to add the following directories to the antivirus exclusion list:

- `D:\Ainos\system-services\ai-daemon\target\release\` (可执行文件 / executables)
- `D:\Ainos\models\` (模型文件 / model files)
- `D:\Ainos\data\` (数据文件 / data files)

---

### 2.2 Linux

#### 前提条件 / Prerequisites

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y build-essential cmake pkg-config libssl-dev \
    python3 python3-pip git curl

# 可选依赖 / Optional dependencies
sudo apt-get install -y libgtk-3-dev libfuse-dev libsystemd-dev \
    linux-headers-$(uname -r)
```

| 软件 / Software | 版本 / Version | 说明 / Description |
|----------------|---------------|-------------------|
| Rust | 1.77+ | 通过 rustup.rs 安装 |
| Python | 3.8+ | 系统包管理器 |
| build-essential | 最新 | GCC/G++ 编译器 |
| CMake | 3.16+ | C++ 构建系统 |
| libssl-dev | 任意 | SSL/TLS 支持 |
| libgtk-3-dev | 任意 | 系统托盘（可选） |
| libfuse-dev | 任意 | AI 文件系统（可选） |
| libsystemd-dev | 任意 | systemd 集成（可选） |
| linux-headers | 匹配内核 | 内核模块构建（可选） |

#### 构建 AI 运行时 / Build AI Runtime (C++)

```bash
cd ai-runtime
cmake -B build -DCMAKE_BUILD_TYPE=Release -DAINOS_BUILD_TESTS=OFF
cmake --build build -j$(nproc)
cmake --install build --prefix /usr/local
```

#### 构建守护进程 / Build Daemon

```bash
cd system-services/ai-daemon
cargo build --release
```

#### Systemd 服务安装 / Systemd Service Installation

正式服务单元文件位于 `platform/linux/systemd/ainos-daemon.service`：

The official service unit file is located at `platform/linux/systemd/ainos-daemon.service`:

```bash
# 复制服务文件 / Copy service files
sudo cp platform/linux/systemd/ainos-daemon.service /etc/systemd/system/
sudo cp platform/linux/systemd/ainos-daemon.sysusers /usr/lib/sysusers.d/
sudo cp platform/linux/systemd/ainos-daemon.tmpfiles /usr/lib/tmpfiles.d/

# 创建系统用户 / Create system user
sudo systemd-sysusers

# 创建运行时目录 / Create runtime directories
sudo systemd-tmpfiles --create

# 重新加载 systemd / Reload systemd
sudo systemctl daemon-reload

# 启用并启动服务 / Enable and start service
sudo systemctl enable --now ainos-daemon
```

服务单元的关键配置 / Key service unit configurations:

```ini
[Service]
Type=notify
User=ainos
Group=ainos
ExecStart=/usr/lib/ainos/ainos-daemon --config /etc/ainos/ainos-daemon.conf
Restart=on-failure
RestartSec=5s

# 安全配置 / Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

# 资源限制 / Resource Limits
MemoryMax=8G
CPUQuota=80%
LimitNOFILE=65536
TasksMax=512
```

#### Unix Domain Socket IPC

在 Linux 上，守护进程默认使用 TCP IPC (`127.0.0.1:9500`)，但也可以配置为使用 Unix Domain Socket 以获得更好的性能和安全性。

On Linux, the daemon uses TCP IPC (`127.0.0.1:9500`) by default, but can be configured to use Unix Domain Sockets for better performance and security.

配置示例 / Configuration example:

```toml
# ai-daemon.conf
socket_path = "/var/run/ainos/ai-daemon.sock"
```

C SDK 自动检测连接类型 / The C SDK auto-detects the connection type:

```c
// TCP 连接 / TCP connection
ainos_ctx *ctx = ainos_init("127.0.0.1:9500");

// Unix Domain Socket 连接 / Unix Domain Socket connection
ainos_ctx *ctx = ainos_init("/var/run/ainos/ai-daemon.sock");
```

#### Cgroups 集成 / Cgroups Integration

AinosOS 提供 cgroups v2 集成，位于 `platform/linux/cgroups/ainos_cgroups.c`（42,680 字节）。

AinosOS provides cgroups v2 integration at `platform/linux/cgroups/ainos_cgroups.c` (42,680 bytes).

功能包括 / Features include:

- CPU 配额管理 / CPU quota management
- 内存限制 / Memory limits
- I/O 带宽控制 / I/O bandwidth control
- PID 限制 / PID limits
- cgroup 命名空间隔离 / cgroup namespace isolation

#### D-Bus 集成 / D-Bus Integration

AinosOS 提供 D-Bus 系统总线集成，位于 `platform/linux/dbus/ainos_dbus.c`（47,860 字节），接口定义在 `platform/linux/dbus/ainos-dbus.xml`。

AinosOS provides D-Bus system bus integration at `platform/linux/dbus/ainos_dbus.c` (47,860 bytes), with interface definition at `platform/linux/dbus/ainos-dbus.xml`.

D-Bus 接口名称 / D-Bus interface name: `com.ainos.Daemon1`

提供的方法 / Methods provided:

- `Status` — 查询守护进程状态 / Query daemon status
- `Infer` — 执行推理 / Execute inference
- `LoadModel` — 加载模型 / Load a model
- `UnloadModel` — 卸载模型 / Unload a model

#### AppArmor 集成 / AppArmor Integration

AppArmor 配置文件位于 `platform/linux/apparmor/usr.local.bin.ainos-daemon`（10,063 字节）。

The AppArmor profile is located at `platform/linux/apparmor/usr.local.bin.ainos-daemon` (10,063 bytes).

```bash
# 安装 AppArmor 配置 / Install AppArmor profile
sudo cp platform/linux/apparmor/usr.local.bin.ainos-daemon /etc/apparmor.d/
sudo apparmor_parser -r /etc/apparmor.d/usr.local.bin.ainos-daemon
```

#### udev 规则 / udev Rules

udev 规则文件位于 `platform/linux/udev/99-ainos.rules`（4,337 字节），用于管理 GPU 和其他硬件加速器的设备权限。

The udev rules file is at `platform/linux/udev/99-ainos.rules` (4,337 bytes), used to manage device permissions for GPUs and other hardware accelerators.

```bash
sudo cp platform/linux/udev/99-ainos.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

#### Snap 包 / Snap Package

Snap 包配置位于 `platform/linux/packaging/snap/snapcraft.yaml`。

The Snap package configuration is at `platform/linux/packaging/snap/snapcraft.yaml`.

```bash
# 构建 Snap 包 / Build Snap package
cd platform/linux/packaging/snap
snapcraft

# 安装 / Install
sudo snap install ainos-daemon_*.snap --dangerous

# 使用 / Usage
ainos-daemon.status
ainos-daemon.infer --model default --prompt "Hello"
```

Snap 包使用 strict confinement，包含以下接口 / The Snap package uses strict confinement with these interfaces:

- `network`, `network-bind` — 网络访问 / Network access
- `process-control` — 进程管理 / Process management
- `system-observe`, `hardware-observe` — 系统观察 / System observation
- `thermal` — 温度传感器 / Thermal sensors
- `dbus`, `dbus-system` — D-Bus 系统总线 / D-Bus system bus
- `docker`, `docker-privileged` — Docker 集成 / Docker integration

#### DEB 包构建 / DEB Package Build

```bash
# 构建 DEB 包 / Build DEB package
bash platform/linux/packaging/build-deb.sh
```

#### RPM 包构建 / RPM Package Build

```bash
# 构建 RPM 包 / Build RPM package
bash platform/linux/packaging/build-rpm.sh
```

---

### 2.3 macOS

#### 前提条件 / Prerequisites

```bash
# 安装 Xcode 命令行工具 / Install Xcode Command Line Tools
xcode-select --install

# 安装 Rust / Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 安装 Python / Install Python (via Homebrew)
brew install python3 cmake
```

#### 构建 / Build

```bash
cd system-services/ai-daemon
cargo build --release
```

#### Launchd 服务管理 / Launchd Service Management

正式 plist 文件位于 `platform/darwin/com.ainos.daemon.plist`。

The official plist file is at `platform/darwin/com.ainos.daemon.plist`.

```bash
# 安装 plist / Install plist
sudo cp platform/darwin/com.ainos.daemon.plist /Library/LaunchDaemons/

# 加载服务 / Load service
sudo launchctl load /Library/LaunchDaemons/com.ainos.daemon.plist

# 启动服务 / Start service
sudo launchctl start com.ainos.daemon

# 停止服务 / Stop service
sudo launchctl stop com.ainos.daemon

# 卸载服务 / Unload service
sudo launchctl unload /Library/LaunchDaemons/com.ainos.daemon.plist

# 查看状态 / Check status
sudo launchctl list | grep ainos
```

#### Launchd Socket Activation

plist 配置了 socket activation，launchd 会创建并传递监听文件描述符，守护进程无需手动绑定端口。

The plist configures socket activation — launchd creates and passes the listening file descriptor, so the daemon does not need to bind the port manually.

```xml
<key>Sockets</key>
<dict>
    <key>Listener</key>
    <dict>
        <key>SockServiceName</key>
        <string>ainos</string>
        <key>SockType</key>
        <string>stream</string>
        <key>SockFamily</key>
        <string>IPv4</string>
        <key>SockNodeName</key>
        <string>127.0.0.1</string>
        <key>SockPort</key>
        <integer>9500</integer>
    </dict>
</dict>
```

使用命令行标志启用 / Enable via command-line flags:

```bash
./target/release/ai-daemon --launchd-sockets
```

#### XPC 传输 / XPC Transport

macOS 平台支持 XPC (XPC Services) 作为 IPC 传输机制。实现位于 `platform/darwin/ainos_xpc.c`（33,111 字节）。

The macOS platform supports XPC (XPC Services) as an IPC transport mechanism. Implementation is at `platform/darwin/ainos_xpc.c` (33,111 bytes).

XPC 服务名称 / XPC service name: `com.ainos.daemon.xpc`

启用 XPC / Enable XPC:

```bash
./target/release/ai-daemon --xpc
```

环境变量 / Environment variable: `AINOS_MACOS_XPC=1`

#### IOKit 热监控 / IOKit Thermal Monitoring

macOS 平台通过 IOKit 接口监控 CPU 温度，实现位于 `platform/darwin/ainos_thermal.c`（50,116 字节）和 `platform/darwin/ainos_thermal.h`（13,598 字节）。

The macOS platform monitors CPU temperature via the IOKit interface, implemented at `platform/darwin/ainos_thermal.c` (50,116 bytes) and `platform/darwin/ainos_thermal.h` (13,598 bytes).

功能包括 / Features include:

- CPU 温度读取 / CPU temperature reading
- 热状态通知 / Thermal state notifications
- 自动降频 / Automatic frequency scaling
- 电源策略调整 / Power policy adjustment

#### macOS 热策略文件 / macOS Thermal Policy

热策略通过 `com.ainos.thermal` XPC 服务管理，plist 中注册了两个 MachService：

Thermal policy is managed via the `com.ainos.thermal` XPC service. Two MachServices are registered in the plist:

```xml
<key>MachServices</key>
<dict>
    <key>com.ainos.daemon.xpc</key>
    <true/>
    <key>com.ainos.thermal</key>
    <true/>
</dict>
```

#### macOS 安装脚本 / macOS Install Script

完整的 macOS 安装脚本位于 `platform/darwin/install.sh`（27,496 字节）。

The complete macOS installation script is at `platform/darwin/install.sh` (27,496 bytes).

```bash
bash platform/darwin/install.sh
```

#### macOS 菜单栏应用 / macOS Menu Bar App

macOS 菜单栏应用位于 `platform/darwin/AinosMenuBar.swift`（40,543 字节），提供系统托盘功能。

The macOS menu bar app is at `platform/darwin/AinosMenuBar.swift` (40,543 bytes), providing system tray functionality.

```bash
# 编译菜单栏应用 / Build menu bar app
swiftc -o AinosMenuBar AinosMenuBar.swift

# 运行 / Run
./AinosMenuBar
```

---

### 2.4 Docker

#### Dockerfile 多阶段构建 / Multi-Stage Docker Build

Dockerfile 使用三阶段构建来最小化最终镜像大小。

The Dockerfile uses three-stage builds to minimize the final image size.

**Stage 0: AI Runtime Builder (C/C++)**

```dockerfile
FROM debian:bookworm-slim AS ai-runtime-builder
RUN apt-get update && apt-get install -y build-essential cmake pkg-config libssl-dev
WORKDIR /build/ai-runtime
COPY ai-runtime/ .
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_ENABLE_GGML=OFF -DAINOS_BUILD_TESTS=OFF \
    && cmake --build build -j$(nproc) \
    && cmake --install build --prefix /install
```

**Stage 1: Daemon Builder (Rust)**

```dockerfile
FROM rust:1.77-slim-bookworm AS daemon-builder
COPY system-services/ai-daemon/ .
RUN cargo build --release
```

**Stage 2: Final Runtime Image**

```dockerfile
FROM debian:bookworm-slim
COPY --from=daemon-builder /install/usr/local/bin/ai-daemon /usr/local/bin/ainos-daemon
COPY --from=ai-runtime-builder /install/lib /usr/lib/
```

#### 构建并使用 Docker 镜像 / Build and Use Docker Image

```bash
# 构建镜像 / Build image
docker build -t ainos-daemon:latest .

# 运行容器 / Run container
docker run -d \
    --name ainos-daemon \
    -p 127.0.0.1:9500:9500 \
    -p 127.0.0.1:9501:9501 \
    -v ainos-models:/var/lib/ainos/models \
    -v ainos-data:/var/lib/ainos/data \
    -v ainos-logs:/var/log/ainos \
    -v $(pwd)/configs/ai-daemon.toml:/etc/ainos/ai-daemon.conf:ro \
    ainos-daemon:latest
```

#### Docker Compose 配置 / Docker Compose Configuration

完整的 docker-compose.yml 定义了三个服务：

The complete docker-compose.yml defines three services:

```yaml
version: "3.9"
services:
  ai-daemon:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "127.0.0.1:9500:9500/tcp"
      - "127.0.0.1:9501:9501/tcp"
    volumes:
      - ainos-models:/var/lib/ainos/models:rw
      - ainos-data:/var/lib/ainos/data:rw
      - ainos-logs:/var/log/ainos:rw
      - ./configs/ai-daemon.toml:/etc/ainos/ai-daemon.conf:ro
    environment:
      - RUST_LOG=${RUST_LOG:-info,ainos=debug}
      - AINOS_HOME=/var/lib/ainos
      - AINOS_AUTH_TOKEN=${AINOS_AUTH_TOKEN:-}
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 8G
          pids: 512
    healthcheck:
      test: ["CMD", "sh", "-c", "echo '{\"type\":\"Status\"}' | timeout 5 nc 127.0.0.1 9500 | grep -q StatusResponse || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    cap_add:
      - SYS_NICE
      - NET_RAW
      - IPC_LOCK
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=100M
      - /var/run/ainos:size=10M
    restart: unless-stopped

  web-panel:
    image: nginx:alpine
    profiles:
      - web
      - full
    ports:
      - "127.0.0.1:9501:80/tcp"
    volumes:
      - ./system-services/web-panel:/usr/share/nginx/html:ro
    depends_on:
      ai-daemon:
        condition: service_healthy

  redis-cache:
    image: redis:7-alpine
    profiles:
      - cache
      - full
    ports:
      - "127.0.0.1:6379:6379/tcp"
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "256mb"]

volumes:
  ainos-models:
  ainos-data:
  ainos-logs:
  ainos-cache:
  ainos-runtime:
```

#### 环境变量配置 / Environment Variables Configuration

| 变量 / Variable | 默认值 / Default | 说明 / Description |
|----------------|-----------------|-------------------|
| `RUST_LOG` | `info,ainos=debug` | 日志级别 / Log level |
| `AINOS_HOME` | `/var/lib/ainos` | 数据目录 / Data directory |
| `AINOS_CONFIG_DIR` | `/etc/ainos` | 配置目录 / Config directory |
| `AINOS_MODELS_DIR` | `/var/lib/ainos/models` | 模型目录 / Models directory |
| `AINOS_CLOUD_API_URL` | — | 云端 API URL / Cloud API URL |
| `AINOS_CLOUD_API_KEY` | — | 云端 API 密钥 / Cloud API key |
| `AINOS_AUTH_ENABLED` | `false` | 启用认证 / Enable auth |
| `AINOS_AUTH_TOKEN` | — | 认证令牌 / Auth token |
| `AINOS_TLS_ENABLED` | `false` | 启用 TLS / Enable TLS |
| `AINOS_POWER_MODE` | `balanced` | 电源模式 / Power mode |
| `AINOS_MEMORY_MAX` | `8G` | 最大内存 / Max memory |
| `AINOS_CPU_QUOTA` | `80%` | CPU 配额 / CPU quota |

#### GPU 直通 / GPU Passthrough

```bash
# NVIDIA GPU
docker run -d --gpus all ainos-daemon:latest

# 或在 docker-compose.yml 中添加
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

---

## 3. 配置 / Configuration

### 3.1 配置文件概览 / Configuration File Overview

配置文件路径 / Configuration file path:

- Windows: `D:\Ainos\configs\ai-daemon.toml`
- Linux: `/etc/ainos/ai-daemon.conf`
- macOS: `/etc/ainos/ai-daemon.conf`
- Docker: `/etc/ainos/ai-daemon.conf` (挂载卷)

配置文件使用 TOML 格式，完整配置项如下：

The configuration file uses TOML format. The complete configuration options are as follows:

```toml
# ============================================
# Ainos AI Daemon Configuration
# ============================================

models_dir = "D:\\Ainos\\models"
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
socket_path = "127.0.0.1:9500"

# Local inference
enable_local = true
local_engine = "ggml"
max_concurrent_inferences = 2
model_cache_size_mb = 4096
inference_timeout_secs = 120

# Cloud fallback (Weelink Platform)
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = ""
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6

# Context management
context_dir = "D:\\Ainos\\data\\contexts"
max_contexts = 1000
context_ttl_days = 30

# Logging
log_level = "debug"
audit_log = "D:\\Ainos\\logs\\audit.log"
audit_all_requests = true

# Authentication
[auth]
enabled = true
token = ""
token_path = "D:\\Ainos\\configs\\auth_token.txt"
session_ttl_seconds = 3600
default_permissions = ["infer", "status", "context"]
audit_log_path = "D:\\Ainos\\logs\\audit.log"
audit_all_requests = true

# Rate limiting
[ratelimit]
enabled = true
infer_rps = 100.0
infer_burst = 200.0
model_rps = 10.0
model_burst = 20.0
status_rps = 1000.0
status_burst = 2000.0
admin_rps = 5.0
admin_burst = 10.0
max_clients = 1000
cleanup_interval_secs = 300

# TLS / Transport Security
[tls]
enabled = false
cert_path = "D:\\Ainos\\certs\\server.crt"
key_path = "D:\\Ainos\\certs\\server.key"
verify_client = false
```

### 3.2 基本配置 / Basic Configuration

```toml
# 模型存储目录 / Models directory
models_dir = "D:\\Ainos\\models"

# 默认模型名称 / Default model name (GGUF format)
default_model = "qwen2.5-0.5b-instruct-q4.gguf"

# IPC Socket 路径 / IPC Socket path
# Windows: TCP 地址 "127.0.0.1:9500"
# Linux: TCP 地址 或 Unix Domain Socket "/var/run/ainos/ai-daemon.sock"
socket_path = "127.0.0.1:9500"
```

- `models_dir`: 存放 GGUF/GGML/ONNX 模型文件的目录路径 / Directory path for model files
- `default_model`: 默认推理使用的模型文件名 / Default model filename for inference
- `socket_path`: IPC 监听地址和端口（TCP）或 Unix Domain Socket 路径 / IPC listen address and port (TCP) or Unix Domain Socket path

### 3.3 本地推理设置 / Local Inference Settings

```toml
# 是否启用本地推理 / Enable local inference
enable_local = true

# 本地推理引擎 / Local inference engine ("ggml" / "onnx")
local_engine = "ggml"

# 最大并行推理数 / Max concurrent inferences
max_concurrent_inferences = 2

# 模型缓存大小 (MB) / Model cache size (MB)
model_cache_size_mb = 4096

# 推理超时 (秒) / Inference timeout (seconds)
inference_timeout_secs = 120
```

- `enable_local`: 启用本地 AI 推理引擎 / Enable the local AI inference engine
- `local_engine`: 选择推理后端 / Select inference backend: `ggml` (GGML/GGUF) 或 `onnx` (ONNX Runtime)
- `max_concurrent_inferences`: 同时运行的推理任务数上限 / Maximum number of concurrent inference tasks
- `model_cache_size_mb`: 模型缓存内存上限（MB） / Maximum model cache memory (MB)
- `inference_timeout_secs`: 单个推理请求的超时时间 / Timeout for a single inference request

### 3.4 云端回退 / Cloud Fallback

```toml
# 是否启用云端回退 / Enable cloud fallback
enable_cloud = true

# 云端 API 端点 / Cloud API endpoint (OpenAI compatible)
cloud_api_url = "https://api.weelinking.com/v1"

# 云端 API Key / Cloud API key
cloud_api_key = ""

# 云端模型名称 / Cloud model name
cloud_model = "gpt-5.6-sol"

# 网络检测间隔 (秒) / Network check interval (seconds)
network_check_interval = 30

# 切换阈值 / Cloud fallback confidence threshold
# 本地推理置信度低于此值则用云端
cloud_fallback_confidence = 0.6
```

- `enable_cloud`: 启用云端推理回退 / Enable cloud inference fallback
- `cloud_api_url`: 兼容 OpenAI API 的端点 URL / OpenAI-compatible API endpoint URL
- `cloud_api_key`: 云端 API 密钥（建议从环境变量读取） / Cloud API key (recommended to read from environment variable)
- `cloud_model`: 云端推理使用的模型名称 / Cloud model name for inference
- `network_check_interval`: 网络可用性检测间隔（秒） / Network availability check interval (seconds)
- `cloud_fallback_confidence`: 当本地推理置信度低于此阈值时自动切换到云端 / Auto-switch to cloud when local inference confidence is below this threshold

### 3.5 上下文管理 / Context Management

```toml
# 上下文存储目录 / Context storage directory
context_dir = "D:\\Ainos\\data\\contexts"

# 最大上下文数 / Maximum number of contexts
max_contexts = 1000

# 上下文 TTL (天) / Context TTL (days)
context_ttl_days = 30
```

- `context_dir`: 上下文数据持久化目录 / Context data persistence directory
- `max_contexts`: 系统保留的最大上下文数量 / Maximum number of contexts retained by the system
- `context_ttl_days`: 上下文过期时间（天），过期后自动清理 / Context expiration time (days), auto-cleaned after expiry

### 3.6 日志设置 / Logging Settings

```toml
# 日志级别 / Log level (trace/debug/info/warn/error)
log_level = "debug"

# 审计日志路径 / Audit log path
audit_log = "D:\\Ainos\\logs\\audit.log"

# 是否记录所有推理请求 / Audit all inference requests
audit_all_requests = true
```

- `log_level`: 控制日志输出详细程度 / Controls log output verbosity
  - `trace`: 最详细，含所有调试信息 / Most verbose, includes all debug info
  - `debug`: 调试信息 / Debug information
  - `info`: 一般信息（推荐生产环境） / General information (recommended for production)
  - `warn`: 仅警告和错误 / Warnings and errors only
  - `error`: 仅错误 / Errors only
- `audit_log`: 审计日志文件路径 / Audit log file path
- `audit_all_requests`: 是否记录所有推理请求到审计日志 / Whether to log all inference requests to the audit log

### 3.7 认证设置 / Authentication Section

```toml
[auth]
enabled = true
token = ""  # auto-generated if empty; set a 64-char hex token for persistence
token_path = "D:\\Ainos\\configs\\auth_token.txt"
session_ttl_seconds = 3600
permissions_file = ""
default_permissions = ["infer", "status", "context"]
audit_log_path = "D:\\Ainos\\logs\\audit.log"
audit_all_requests = true
```

- `enabled`: 启用认证 / Enable authentication
- `token`: 预共享令牌（空时自动生成） / Pre-shared token (auto-generated if empty)
- `token_path`: 令牌文件路径（自动生成时写入） / Token file path (written when auto-generated)
- `session_ttl_seconds`: 会话有效期（秒） / Session TTL (seconds)
- `default_permissions`: 默认权限列表 / Default permissions list
  - `infer`: 推理权限 / Inference permission
  - `status`: 状态查询 / Status query
  - `context`: 上下文管理 / Context management
  - `admin`: 管理操作 / Admin operations
- `audit_log_path`: 审计日志路径（可覆盖顶层设置） / Audit log path (can override top-level setting)
- `audit_all_requests`: 记录所有请求到审计日志 / Log all requests to audit log

### 3.8 速率限制 / Rate Limiting

```toml
[ratelimit]
enabled = true
infer_rps = 100.0
infer_burst = 200.0
model_rps = 10.0
model_burst = 20.0
status_rps = 1000.0
status_burst = 2000.0
admin_rps = 5.0
admin_burst = 10.0
max_clients = 1000
cleanup_interval_secs = 300
```

- `enabled`: 启用速率限制 / Enable rate limiting
- `infer_rps` / `infer_burst`: 推理请求速率限制（请求/秒） / Inference request rate limit (requests/sec)
- `model_rps` / `model_burst`: 模型管理操作速率限制 / Model management operation rate limit
- `status_rps` / `status_burst`: 状态查询速率限制 / Status query rate limit
- `admin_rps` / `admin_burst`: 管理操作速率限制 / Admin operation rate limit
- `max_clients`: 最大并发客户端数 / Maximum concurrent clients
- `cleanup_interval_secs`: 过期客户端清理间隔（秒） / Expired client cleanup interval (seconds)

### 3.9 TLS 设置 / TLS Section

```toml
[tls]
enabled = false
cert_path = "D:\\Ainos\\certs\\server.crt"
key_path = "D:\\Ainos\\certs\\server.key"
verify_client = false
```

- `enabled`: 启用 TLS 加密 / Enable TLS encryption
- `cert_path`: 服务器证书路径 / Server certificate path
- `key_path`: 服务器私钥路径 / Server private key path
- `verify_client`: 是否验证客户端证书 / Whether to verify client certificates

启用 TLS 需要编译时包含 `tls` feature / Enabling TLS requires the `tls` feature at compile time:

```bash
cargo build --release --features tls
```

### 3.10 环境变量覆盖 / Environment Variable Overrides

以下环境变量可以覆盖配置文件中的设置：

The following environment variables can override configuration file settings:

| 环境变量 / Variable | 覆盖项 / Overrides | 示例 / Example |
|-------------------|-------------------|---------------|
| `AINOS_HOME` | 基础数据目录 / Base data directory | `/var/lib/ainos` |
| `AINOS_AUTH_TOKEN` | `[auth].token` | `abcdef123456...` |
| `AINOS_CONFIG_DIR` | 配置目录 / Config directory | `/etc/ainos` |
| `AINOS_MODELS_DIR` | `models_dir` | `/var/lib/ainos/models` |
| `AINOS_DATA_DIR` | `context_dir` | `/var/lib/ainos/data` |
| `AINOS_LOG_DIR` | 日志目录 / Log directory | `/var/log/ainos` |
| `AINOS_CLOUD_API_URL` | `cloud_api_url` | `https://api.example.com/v1` |
| `AINOS_CLOUD_API_KEY` | `cloud_api_key` | `sk-...` |
| `AINOS_POWER_MODE` | 电源模式 / Power mode | `balanced` |
| `RUST_LOG` | `log_level` | `debug` |

---

## 4. 首次推理 / First Inference

### 4.1 下载模型 / Download a Model

```bash
# 列出可用的模型 / List available models
python scripts/download_model.py --list
```

输出示例 / Example output:

```
可用的预配置模型:
======================================================================

  qwen2.5-0.5b: Qwen2.5 0.5B Instruct - 轻量级中文模型
    仓库: Qwen/Qwen2.5-0.5B-Instruct-GGUF
    [ ] q4_0       → qwen2.5-0.5b-instruct-q4_0.gguf
    [ ] q4_k_m     → qwen2.5-0.5b-instruct-q4_k_m.gguf
    [ ] q8_0       → qwen2.5-0.5b-instruct-q8_0.gguf

  phi-3-mini: Phi-3 Mini 4K - 微软小模型，英文优秀
    仓库: microsoft/Phi-3-mini-4k-instruct-gguf
    [ ] q4_0       → Phi-3-mini-4k-instruct-q4.gguf
    [ ] q4_k_m     → Phi-3-mini-4k-instruct-q4_k_m.gguf

  llama-3.2-1b: Llama 3.2 1B - 超轻量英文模型
    仓库: huggingface/llama-3.2-1b-gguf
    [ ] q4_0       → llama-3.2-1b-q4_0.gguf
    [ ] q8_0       → llama-3.2-1b-q8_0.gguf
```

下载模型 / Download a model:

```bash
# 使用预配置模型名 / Use a known model name
python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0

# 或直接从 HuggingFace 下载 / Or download directly from HuggingFace
python scripts/download_model.py --model Qwen/Qwen2.5-0.5B-Instruct-GGUF --quantization q4_0
```

下载支持断点续传和进度显示 / Download supports resumable downloads and progress display:

```
下载 qwen2.5-0.5b (q4_0)
  仓库: Qwen/Qwen2.5-0.5B-Instruct-GGUF
  文件: qwen2.5-0.5b-instruct-q4_0.gguf
  大小: 352.0MB | 下载中...
   256.0MB / 352.0MB (72.7%) | 12.5 MB/s
   352.0MB / 352.0MB (100.0%) | 11.8 MB/s
  ✓ 下载完成: qwen2.5-0.5b-instruct-q4_0.gguf
  ✓ SHA256 校验通过
```

### 4.2 启动守护进程 / Start the Daemon

```bash
# Windows
cd D:\Ainos\system-services\ai-daemon
target\release\ai-daemon.exe -c ..\..\configs\ai-daemon.toml -v

# Linux/macOS
cd system-services/ai-daemon
./target/release/ai-daemon -c ../../configs/ai-daemon.toml -v

# Docker
docker-compose up -d
```

守护进程启动后会输出日志 / The daemon outputs logs on startup:

```
2024-01-01T12:00:00.000Z INFO  ainos::config > Loading configuration from configs/ai-daemon.toml
2024-01-01T12:00:00.001Z INFO  ainos::runtime > Initializing AI runtime (engine: ggml)
2024-01-01T12:00:00.002Z INFO  ainos::models > Scanning models directory: D:\Ainos\models
2024-01-01T12:00:00.010Z INFO  ainos::models > Found 1 model(s)
2024-01-01T12:00:00.010Z INFO  ainos::models >   - qwen2.5-0.5b-instruct-q4.gguf (352.0 MB)
2024-01-01T12:00:00.011Z INFO  ainos::cache > Initialized semantic cache (LRU, 1000 entries)
2024-01-01T12:00:00.012Z INFO  ainos::ipc > IPC server listening on 127.0.0.1:9500
2024-01-01T12:00:00.012Z INFO  ainos::thermal > Thermal monitor started (adaptive polling)
2024-01-01T12:00:00.013Z INFO  ainos::daemon > Ainos AI Daemon v0.1.0 ready
```

### 4.3 Python SDK 推理示例 / Python SDK Inference Example

```python
from ainos import AinosClient

# 创建客户端并连接 / Create client and connect
client = AinosClient(host="127.0.0.1", port=9500)
client.connect()

# 查询系统状态 / Query system status
status = client.status()
print(f"Uptime: {status.uptime}s")
print(f"Models loaded: {status.models_loaded}")

# 执行推理 / Run inference
resp = client.infer(
    prompt="What is Ainos OS?",
    model="default",
    temperature=0.7,
    max_tokens=256,
)

print(f"Response: {resp.output}")
print(f"Tokens: {resp.tokens_generated}")
print(f"Time: {resp.inference_ms}ms")
print(f"Source: {resp.source}")

# 断开连接 / Disconnect
client.disconnect()
```

使用上下文管理器（自动连接/断开） / Using context manager (auto connect/disconnect):

```python
from ainos import AinosClient

with AinosClient() as client:
    status = client.status()
    print(f"Daemon uptime: {status.uptime}s")

    resp = client.infer("Hello, Ainos!")
    print(f"AI says: {resp.output}")
```

完整示例代码位于 / Complete example code at: `userland/sdk/python/examples/basic_usage.py`

### 4.4 C SDK 推理示例 / C SDK Inference Example

```c
#include <stdio.h>
#include "ainos.h"

int main() {
    ainos_ctx *ctx = ainos_init("127.0.0.1:9500");
    if (!ctx) {
        printf("Failed to initialize SDK\n");
        return 1;
    }

    int ret = ainos_connect(ctx);
    if (ret != AINOS_OK) {
        printf("Failed to connect to daemon\n");
        ainos_destroy(ctx);
        return 1;
    }

    // 查询系统信息 / Query system info
    ainos_resp *info = ainos_get_info(ctx);
    if (info && !info->error_code) {
        printf("System info: %s\n", info->output);
        ainos_resp_free(info);
    }

    // 执行推理 / Run inference
    ainos_infer_opts opts = AINOS_INFER_OPTS_DEFAULT;
    opts.temperature = 0.7f;
    opts.max_tokens = 100;

    ainos_resp *resp = ainos_infer(ctx, "default",
        "What is Ainos OS?", &opts);
    if (resp && !resp->error_code) {
        printf("Response: %s\n", resp->output);
        printf("Tokens: %d\n", resp->tokens_generated);
        printf("Time: %lld ms\n", resp->inference_ms);
        printf("Source: %s\n", resp->source);
        ainos_resp_free(resp);
    }

    ainos_destroy(ctx);
    return 0;
}
```

编译 / Compile:

```bash
# Windows
gcc -o ainos_test ainos_test.c -L. -lainos -lws2_32

# Linux
gcc -o ainos_test ainos_test.c -L. -lainos -lpthread
```

### 4.5 Web 面板推理 / Web Panel Inference

1. 启动 Web 服务器 / Start the web server:
   ```bash
   python system-services/web-panel/web_server.py
   ```

2. 打开浏览器访问 / Open browser to: http://127.0.0.1:9501

3. Web 面板提供 5 个页面 / The web panel provides 5 pages:
   - **Dashboard** — 系统状态总览 / System status overview
   - **Inference** — 推理测试界面 / Inference test interface
   - **Models** — 模型管理 / Model management
   - **Context** — 上下文查看 / Context viewer
   - **Logs** — 日志查看 / Log viewer

4. 在推理页面输入提示词并点击"Submit" / On the inference page, enter a prompt and click "Submit"

### 4.6 查看结果 / Viewing Results

推理结果包含以下字段 / The inference result contains the following fields:

| 字段 / Field | 类型 / Type | 说明 / Description |
|-------------|-----------|-------------------|
| `output` | string | 生成的文本 / Generated text |
| `tokens_generated` | int | 生成的 token 数 / Number of tokens generated |
| `inference_ms` | int | 推理耗时（毫秒） / Inference time (milliseconds) |
| `source` | string | 推理来源：`local` 或 `cloud` / Inference source |
| `model` | string | 使用的模型名称 / Model name used |

### 4.7 理解响应结构 / Understanding the Response

IPC 协议使用 JSON 行协议，所有请求和响应均为单行 JSON，以 `\n` 分隔。

The IPC protocol uses JSON lines (NDJSON). All requests and responses are single-line JSON terminated by `\n`.

**请求格式 / Request Format:**

```json
{"type":"Inference","model":"default","prompt":"Hello!","temperature":0.7,"max_tokens":256}
```

**响应格式 / Response Format:**

```json
{
    "type": "InferenceResponse",
    "output": "Hello! Ainos OS is an AI-native operating system...",
    "tokens_generated": 42,
    "inference_ms": 1234,
    "source": "local",
    "model": "qwen2.5-0.5b-instruct-q4.gguf"
}
```

**支持的 IPC 操作 / Supported IPC Operations:**

| 操作 / Operation | 说明 / Description | 请求参数 / Request Parameters | 响应类型 / Response Type |
|-----------------|-------------------|------------------------------|------------------------|
| Status | 系统状态查询 / System status | — | StatusResponse |
| Inference | 推理请求 / Inference request | model, prompt, temperature, max_tokens | InferenceResponse |
| ContextStore | 存储上下文 / Store context | key, value | InferenceResponse |
| ContextRetrieve | 检索上下文 / Retrieve context | key | InferenceResponse |
| ModelList | 模型列表 / List models | — | ModelListResponse |
| ModelLoad | 加载模型 / Load model | path | InferenceResponse |
| ModelUnload | 卸载模型 / Unload model | model_id | InferenceResponse |
| Auth | 认证 / Authentication | token | AuthResponse |
| RateLimitStatus | 速率限制状态 / Rate limit status | — | RateLimitResponse |

---

## 5. 模型管理 / Model Management

### 5.1 模型存放位置 / Where to Place Models

模型文件存放在 `models_dir` 配置项指定的目录中：

Model files are stored in the directory specified by the `models_dir` configuration option:

- Windows: `D:\Ainos\models\`
- Linux: `/var/lib/ainos/models/`
- macOS: `/usr/local/lib/ainos/models/`
- Docker: `/var/lib/ainos/models/` (挂载卷)

### 5.2 支持的格式 / Supported Formats

| 格式 / Format | 引擎 / Engine | 说明 / Description |
|--------------|-------------|-------------------|
| GGUF | GGML | 推荐格式，GGML 通用格式 / Recommended format, GGML universal format |
| GGML | GGML | 旧格式，兼容 GGML 模型 / Legacy format, compatible with GGML models |
| ONNX | ONNX Runtime | 可选，ONNX Runtime 后端 / Optional, ONNX Runtime backend |

### 5.3 通过 IPC 加载模型 / Loading Models via IPC

Python SDK:

```python
from ainos import AinosClient

client = AinosClient()
client.connect()

# 加载模型 / Load a model
result = client.model_load("/var/lib/ainos/models/qwen2.5-0.5b-instruct-q4.gguf")
print(f"Model loaded: {result['model_id']}")
print(f"Status: {result['status']}")

client.disconnect()
```

C SDK:

```c
ainos_ctx *ctx = ainos_init("127.0.0.1:9500");
ainos_connect(ctx);

int ret = ainos_model_load(ctx, "/var/lib/ainos/models/qwen2.5-0.5b-instruct-q4.gguf");
if (ret == AINOS_OK) {
    printf("Model loaded successfully\n");
}

ainos_destroy(ctx);
```

原始 IPC 请求 / Raw IPC Request:

```json
{"type":"ModelLoad","path":"/var/lib/ainos/models/qwen2.5-0.5b-instruct-q4.gguf"}
```

### 5.4 列出可用模型 / Listing Available Models

Python SDK:

```python
from ainos import AinosClient

client = AinosClient()
client.connect()

models = client.model_list()
for m in models:
    loaded = "LOADED" if m.loaded else "unloaded"
    print(f"  - {m.name} ({m.size_mb} MB) [{loaded}]")
    print(f"    id: {m.id}, arch: {m.architecture}")

client.disconnect()
```

C SDK:

```c
ainos_resp *resp = ainos_get_info(ctx);
if (resp && !resp->error_code) {
    printf("Models: %s\n", resp->output);
    ainos_resp_free(resp);
}
```

原始 IPC 请求 / Raw IPC Request:

```json
{"type":"ModelList"}
```

响应示例 / Example Response:

```json
{
    "type": "ModelListResponse",
    "models": [
        {
            "name": "qwen2.5-0.5b-instruct-q4.gguf",
            "id": "qwen2.5-0.5b-instruct-q4",
            "architecture": "qwen2",
            "size_mb": 352.0,
            "loaded": true,
            "quantization": "q4_0"
        }
    ]
}
```

### 5.5 卸载模型 / Unloading Models

Python SDK:

```python
from ainos import AinosClient

client = AinosClient()
client.connect()

result = client.model_unload("qwen2.5-0.5b-instruct-q4")
print(f"Unloaded: {result['status']}")

client.disconnect()
```

C SDK:

```c
int ret = ainos_model_unload(ctx, "qwen2.5-0.5b-instruct-q4");
if (ret == AINOS_OK) {
    printf("Model unloaded\n");
}
```

原始 IPC 请求 / Raw IPC Request:

```json
{"type":"ModelUnload","model_id":"qwen2.5-0.5b-instruct-q4"}
```

### 5.6 默认模型配置 / Default Model Configuration

在配置文件中设置默认模型 / Set the default model in the configuration file:

```toml
default_model = "qwen2.5-0.5b-instruct-q4.gguf"
```

当推理请求中指定 `model="default"` 时，守护进程会自动使用默认模型。

When the inference request specifies `model="default"`, the daemon automatically uses the default model.

### 5.7 模型下载脚本使用说明 / Model Download Script Usage

`scripts/download_model.py` 支持多种下载方式 / supports multiple download methods:

```bash
# 列出所有可用模型 / List all available models
python scripts/download_model.py --list

# 使用预配置模型名下载 / Download using known model name
python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0

# 直接从 HuggingFace 仓库下载 / Download directly from HuggingFace repo
python scripts/download_model.py --model Qwen/Qwen2.5-0.5B-Instruct-GGUF --quantization q4_0

# 指定输出目录 / Specify output directory
python scripts/download_model.py --known qwen2.5-0.5b --output D:/Ainos/my_models
```

预配置模型清单 / Pre-configured Model List:

| 名称 / Name | 仓库 / Repository | 说明 / Description |
|------------|------------------|-------------------|
| `qwen2.5-0.5b` | Qwen/Qwen2.5-0.5B-Instruct-GGUF | 轻量级中文模型 / Lightweight Chinese model |
| `phi-3-mini` | microsoft/Phi-3-mini-4k-instruct-gguf | 微软小模型，英文优秀 / Microsoft small model, excellent English |
| `llama-3.2-1b` | huggingface/llama-3.2-1b-gguf | 超轻量英文模型 / Ultra-lightweight English model |

下载脚本特性 / Download Script Features:

- **断点续传** / Resumable downloads — 使用 HTTP Range 请求 / Uses HTTP Range requests
- **进度显示** / Progress display — 实时显示下载速度和百分比 / Real-time speed and percentage display
- **SHA256 校验** / SHA256 verification — 下载完成后自动验证文件完整性 / Auto-verifies file integrity after download
- **模型清单** / Model manifest — 自动更新 `model_manifest.json` / Auto-updates `model_manifest.json`

---

## 6. 故障排除 / Troubleshooting

### 6.1 守护进程无法启动 / Daemon Won't Start

#### 症状 / Symptoms

```
error: target\release\ai-daemon.exe: The system cannot find the path specified.
```

#### 检查项 / Check Items

1. **配置文件路径** / **Config file path**
   - 确认配置文件存在且路径正确 / Verify the config file exists and the path is correct
   - 使用 `-c` 参数指定配置文件路径 / Use the `-c` flag to specify the config path

2. **端口可用性** / **Port availability**
   - 检查端口 9500 是否被占用 / Check if port 9500 is already in use
   ```bash
   # Windows
   netstat -ano | findstr :9500
   # Linux/macOS
   lsof -i :9500
   ```
   - 如果端口被占用，修改 `socket_path` 配置项 / If the port is in use, modify the `socket_path` config

3. **日志文件** / **Log files**
   - 检查日志文件获取详细信息 / Check log files for details
   - Windows: `D:\Ainos\logs\daemon.log`
   - Linux: `/var/log/ainos/daemon.log` 或 `journalctl -u ai-daemon`
   - macOS: `/var/log/ainos/daemon-stdout.log`

4. **权限问题** / **Permission issues**
   - Windows: 确保以管理员权限运行 / Ensure running with administrator privileges
   - Linux: 确保 `ainos` 用户有目录访问权限 / Ensure the `ainos` user has directory access permissions
   - macOS: 确保 root 权限运行 launchd 服务 / Ensure running launchd service with root privileges

#### 解决方案 / Solutions

```bash
# 检查配置文件语法 / Check config file syntax
# 确保 TOML 格式正确 / Ensure TOML format is correct

# 手动指定配置路径 / Manually specify config path
./target/release/ai-daemon -c /path/to/ai-daemon.toml -v

# 启用调试日志 / Enable debug logging
RUST_LOG=debug ./target/release/ai-daemon -c ai-daemon.toml -v
```

### 6.2 连接被拒绝 / Connection Refused

#### 症状 / Symptoms

```
AinosConnectionError: Cannot connect to 127.0.0.1:9500 — [Errno 111] Connection refused
```

#### 检查项 / Check Items

1. **守护进程是否运行** / **Is the daemon running?**
   ```bash
   # Windows
   tasklist | findstr ai-daemon
   # Linux/macOS
   ps aux | grep ai-daemon
   # Docker
   docker ps | grep ainos-daemon
   ```

2. **端口和地址是否正确** / **Is the port and address correct?**
   - 默认地址: `127.0.0.1:9500`
   - 检查配置中的 `socket_path` 是否匹配 / Check if `socket_path` in config matches

3. **防火墙是否阻止** / **Is the firewall blocking?**
   - Windows: 检查 Windows Defender 防火墙 / Check Windows Defender Firewall
   - Linux: 检查 iptables/nftables 规则 / Check iptables/nftables rules

#### 解决方案 / Solutions

```bash
# 启动守护进程 / Start the daemon
./target/release/ai-daemon -c ai-daemon.toml -v

# 测试连接 / Test connection
python -c "
import socket
s = socket.socket()
s.settimeout(3)
s.connect(('127.0.0.1', 9500))
s.sendall(b'{\"type\":\"Status\"}\n')
print(s.recv(4096))
s.close()
"
```

### 6.3 认证失败 / Authentication Failed

#### 症状 / Symptoms

```
AinosAuthError: Authentication failed
```

#### 检查项 / Check Items

1. **令牌是否正确** / **Is the token correct?**
   - 检查配置文件中的 `[auth].token` / Check `[auth].token` in config
   - 检查环境变量 `AINOS_AUTH_TOKEN` / Check the `AINOS_AUTH_TOKEN` environment variable

2. **令牌文件是否存在** / **Does the token file exist?**
   - 检查 `token_path` 指定的文件 / Check the file specified by `token_path`
   - 如果令牌为空，守护进程会自动生成并写入 `token_path` / If the token is empty, the daemon auto-generates and writes to `token_path`

#### 解决方案 / Solutions

```bash
# 查看自动生成的令牌 / View the auto-generated token
cat D:\Ainos\configs\auth_token.txt

# 设置环境变量令牌 / Set the token via environment variable
set AINOS_AUTH_TOKEN=your-64-char-hex-token

# 在配置中设置令牌 / Set the token in config
# [auth]
# token = "your-64-char-hex-token"
```

### 6.4 模型未找到 / Model Not Found

#### 症状 / Symptoms

```
AinosError: Model not found: qwen2.5-0.5b-instruct-q4.gguf
```

#### 检查项 / Check Items

1. **模型文件是否存在** / **Does the model file exist?**
   ```bash
   # Windows
   dir D:\Ainos\models\*.gguf
   # Linux
   ls /var/lib/ainos/models/*.gguf
   ```

2. **文件权限是否正确** / **Are file permissions correct?**
   - Linux: 确保 `ainos` 用户可读模型文件 / Ensure the `ainos` user can read model files
   ```bash
   sudo chown -R ainos:ainos /var/lib/ainos/models
   sudo chmod -R 644 /var/lib/ainos/models/*.gguf
   ```

3. **配置中的默认模型名是否匹配** / **Does the default model name in config match?**
   - 检查 `default_model` 是否与文件名完全一致（包括大小写和扩展名） / Check if `default_model` exactly matches the filename (case and extension)

#### 解决方案 / Solutions

```bash
# 下载模型 / Download a model
python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0

# 手动指定模型路径 / Manually specify model path
# 在推理请求中使用完整路径 / Use the full path in the inference request
# 或在配置中更新 default_model / Or update default_model in config
```

### 6.5 推理超时 / Inference Timeout

#### 症状 / Symptoms

```
AinosTimeoutError: Read timed out after 120s
```

#### 原因 / Causes

- 模型文件过大，加载时间过长 / Model file is too large, loading takes too long
- 系统资源不足（CPU/内存） / Insufficient system resources (CPU/memory)
- 云端推理网络延迟高 / High network latency for cloud inference

#### 解决方案 / Solutions

```toml
# 增加推理超时时间 / Increase inference timeout
inference_timeout_secs = 300

# 减少模型缓存大小 / Reduce model cache size
model_cache_size_mb = 2048

# 降低并行推理数 / Reduce concurrent inferences
max_concurrent_inferences = 1
```

### 6.6 内存不足 / Out of Memory

#### 症状 / Symptoms

```
error: Memory allocation failed for model
```

#### 原因 / Causes

- 模型文件过大，无法加载到内存 / Model file too large to load into memory
- 模型缓存配置过高 / Model cache configured too high
- 系统物理内存不足 / Insufficient system physical memory

#### 解决方案 / Solutions

```toml
# 减少模型缓存大小 / Reduce model cache size
model_cache_size_mb = 1024

# 减少并行推理数 / Reduce concurrent inferences
max_concurrent_inferences = 1
```

**使用量化模型 / Use Quantized Models:**

不同量化级别所需内存 / Memory requirements for different quantization levels:

| 量化 / Quantization | 模型大小 / Model Size | 内存需求 / Memory Requirement |
|--------------------|---------------------|------------------------------|
| q4_0 (4-bit) | ~350 MB | ~512 MB |
| q4_k_m (4-bit) | ~380 MB | ~512 MB |
| q8_0 (8-bit) | ~700 MB | ~1 GB |
| FP16 | ~1.4 GB | ~2 GB |

```bash
# 下载更小量化的模型 / Download a smaller quantized model
python scripts/download_model.py --known qwen2.5-0.5b --quantization q4_0
```

### 6.7 热节流 / Thermal Throttling

#### 症状 / Symptoms

```
2024-01-01T12:00:00.000Z WARN ainos::thermal > CPU temperature: 92°C, switching to EFFICIENT mode
2024-01-01T12:00:00.000Z WARN ainos::thermal > CPU temperature: 98°C, switching to EMERGENCY mode
```

#### 电源策略模式 / Power Policy Modes

| 模式 / Mode | 温度 / Temperature | 线程 / Threads | 精度 / Precision | 延迟 / Latency |
|------------|-------------------|---------------|-----------------|---------------|
| MAX | <70°C | 4 核 | FP32 | 5ms |
| BALANCED | 70-85°C | 2 核 | FP16 | 10ms |
| EFFICIENT | 85-95°C | 1 核 | INT8 | 20ms |
| EMERGENCY | >95°C | 1 核 | INT4 | 40ms |

#### 解决方案 / Solutions

```bash
# 检查 CPU 温度 / Check CPU temperature
# Linux
cat /sys/class/thermal/thermal_zone*/temp
# macOS
pmset -g therm

# 改善散热 / Improve cooling
# - 清理风扇和散热片 / Clean fans and heatsinks
# - 降低环境温度 / Reduce ambient temperature
# - 使用笔记本散热垫 / Use a laptop cooling pad

# 手动设置电源模式 / Manually set power mode
# 在配置中设置 / Set in config:
# AINOS_POWER_MODE=balanced
```

### 6.8 速率限制超出 / Rate Limit Exceeded

#### 症状 / Symptoms

```
AinosError: Rate limit exceeded for category 'infer'. Try again in 0.5 seconds.
```

#### 速率限制配置 / Rate Limit Configuration

```toml
[ratelimit]
infer_rps = 100.0       # 推理请求/秒 / Inference requests per second
infer_burst = 200.0      # 推理突发上限 / Inference burst limit
model_rps = 10.0         # 模型操作/秒 / Model operations per second
status_rps = 1000.0      # 状态查询/秒 / Status queries per second
admin_rps = 5.0          # 管理操作/秒 / Admin operations per second
```

#### 解决方案 / Solutions

```python
import time

# 在请求之间添加延迟 / Add delay between requests
resp1 = client.infer("Prompt 1")
time.sleep(0.1)  # 100ms 间隔 / 100ms interval
resp2 = client.infer("Prompt 2")

# 或增加速率限制 / Or increase rate limits
# 在配置中调整 / Adjust in config:
# infer_rps = 200.0
# infer_burst = 400.0
```

### 6.9 Windows 特定问题 / Windows Specific Issues

#### 防火墙阻止 / Firewall Blocking

```batch
REM 添加入站规则 / Add inbound rule
netsh advfirewall firewall add rule name="Ainos AI Daemon" dir=in action=allow protocol=TCP localport=9500

REM 检查现有规则 / Check existing rules
netsh advfirewall firewall show rule name="Ainos AI Daemon"
```

#### 杀毒软件干扰 / Antivirus Interference

将以下目录添加到排除列表 / Add these directories to the exclusion list:

- `D:\Ainos\` (整个项目目录 / The entire project directory)
- 或仅排除 / Or exclude only:
  - `D:\Ainos\system-services\ai-daemon\target\`
  - `D:\Ainos\models\`

#### 命名管道权限 / Named Pipe Permissions

```batch
REM 如果使用命名管道 IPC，确保管道权限正确
REM Named pipe 名称: \\.\pipe\ainos-daemon
```

#### Windows 服务问题 / Windows Service Issues

```batch
REM 查看服务状态 / Check service status
sc query AinosDaemon

REM 查看服务详细状态 / Check service detailed status
sc qc AinosDaemon

REM 手动启动服务 / Manually start service
net start AinosDaemon

REM 查看服务日志 / Check service logs
# 事件查看器 -> Windows 日志 -> 应用程序
```

### 6.10 Linux 特定问题 / Linux Specific Issues

#### 内核模块加载 / Kernel Module Loading

```bash
# 检查内核模块是否已加载 / Check if kernel modules are loaded
lsmod | grep ainos

# 手动加载模块 / Manually load modules
cd kernel
sudo make load-ai

# 检查内核版本是否匹配 / Check if kernel version matches
uname -r
# 确保 linux-headers 版本与运行内核一致 / Ensure linux-headers version matches running kernel
```

#### Sysfs 权限 / Sysfs Permissions

```bash
# 温度传感器权限 / Thermal sensor permissions
ls -l /sys/class/thermal/thermal_zone*/temp
# 确保 ainos 用户可读 / Ensure ainos user can read
sudo chmod 644 /sys/class/thermal/thermal_zone*/temp

# 或使用 udev 规则 / Or use udev rules
# 已包含在 platform/linux/udev/99-ainos.rules 中
```

#### Cgroups 配置 / Cgroups Configuration

```bash
# 检查 cgroups v2 是否启用 / Check if cgroups v2 is enabled
grep cgroup /proc/filesystems

# 检查 cgroups 挂载点 / Check cgroups mount point
mount | grep cgroup

# 如果使用 cgroups v1，需要手动配置 / If using cgroups v1, manual configuration needed
# 见内核启动参数 / See kernel boot parameters:
# systemd.unified_cgroup_hierarchy=1
```

#### Systemd 服务问题 / Systemd Service Issues

```bash
# 查看服务状态 / Check service status
sudo systemctl status ai-daemon

# 查看详细日志 / View detailed logs
sudo journalctl -u ai-daemon -x -e

# 查看服务启动超时 / Check service startup timeout
sudo journalctl -u ai-daemon | grep "Timed out"

# 重新加载配置并重启 / Reload config and restart
sudo systemctl daemon-reload
sudo systemctl restart ai-daemon
```

### 6.11 macOS 特定问题 / macOS Specific Issues

#### Launchd Plist 问题 / Launchd Plist Issues

```bash
# 检查 plist 语法 / Check plist syntax
plutil -lint /Library/LaunchDaemons/com.ainos.daemon.plist

# 检查服务是否已加载 / Check if service is loaded
sudo launchctl list | grep ainos

# 如果服务显示 "not found"，重新加载 / If service shows "not found", reload
sudo launchctl unload /Library/LaunchDaemons/com.ainos.daemon.plist
sudo launchctl load /Library/LaunchDaemons/com.ainos.daemon.plist
```

#### 热策略问题 / Thermal Policy Issues

```bash
# 检查系统热状态 / Check system thermal state
pmset -g therm

# 检查 CPU 温度 / Check CPU temperature
sudo powermetrics --samplers smc -i 1000 -n 1 | grep "CPU die"

# 手动重置热策略 / Manually reset thermal policy
sudo pmset -a powernap 0
```

#### XPC 权限问题 / XPC Permissions Issues

```bash
# 确保 XPC 服务已注册 / Ensure XPC service is registered
# 在 plist 中检查 MachServices 配置 / Check MachServices in plist

# XPC 服务需要 root 权限 / XPC service requires root privileges
# 确保以 root 运行 / Ensure running as root
```

### 6.12 Docker 特定问题 / Docker Specific Issues

#### 卷挂载问题 / Volume Mount Issues

```bash
# 检查卷是否已创建 / Check if volumes are created
docker volume ls | grep ainos

# 检查卷挂载点 / Check volume mount points
docker inspect ainos-daemon | grep Mounts

# 确保主机目录存在 / Ensure host directories exist
mkdir -p ./models ./data ./logs

# 检查权限 / Check permissions
# 容器内使用 UID 1000，确保主机目录可写
chown -R 1000:1000 ./models ./data ./logs
```

#### GPU 直通问题 / GPU Passthrough Issues

```bash
# 检查 NVIDIA Container Toolkit / Check NVIDIA Container Toolkit
which nvidia-smi
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# 在 docker-compose.yml 中启用 GPU / Enable GPU in docker-compose.yml
# deploy:
#   resources:
#     reservations:
#       devices:
#         - driver: nvidia
#           count: 1
#           capabilities: [gpu]
```

#### 网络问题 / Network Issues

```bash
# 检查端口映射 / Check port mapping
docker port ainos-daemon

# 从宿主机测试连接 / Test connection from host
nc -zv 127.0.0.1 9500

# 检查容器内网络 / Check container network
docker exec ainos-daemon nc -zv 127.0.0.1 9500
```

#### 健康检查问题 / Health Check Issues

```bash
# 查看健康检查状态 / Check health check status
docker inspect --format='{{.State.Health.Status}}' ainos-daemon

# 查看健康检查日志 / Check health check logs
docker inspect --format='{{.State.Health.Log}}' ainos-daemon

# 手动执行健康检查命令 / Manually run health check command
docker exec ainos-daemon sh -c "echo '{\"type\":\"Status\"}' | timeout 5 nc 127.0.0.1 9500"
```

### 6.13 日志文件位置 / Log File Locations

| 平台 / Platform | 守护进程日志 / Daemon Log | 审计日志 / Audit Log |
|----------------|-------------------------|---------------------|
| Windows | `D:\Ainos\logs\daemon.log` | `D:\Ainos\logs\audit.log` |
| Linux | `/var/log/ainos/daemon.log` 或 `journalctl -u ai-daemon` | `/var/log/ainos/audit.log` |
| macOS | `/var/log/ainos/daemon-stdout.log` | `/var/log/ainos/audit.log` |
| Docker | `docker logs ainos-daemon` | `/var/log/ainos/audit.log` |

### 6.14 调试模式 / Debug Mode

```bash
# 使用 -v 标志启用详细输出 / Enable verbose output with -v flag
./target/release/ai-daemon -c ai-daemon.toml -v

# 使用 RUST_LOG 环境变量控制日志级别 / Use RUST_LOG env var to control log level
RUST_LOG=trace ./target/release/ai-daemon -c ai-daemon.toml -v

# 只查看特定模块的日志 / View logs for specific modules only
RUST_LOG=ainos::ipc=debug,ainos::thermal=info ./target/release/ai-daemon -c ai-daemon.toml

# 日志级别说明 / Log level explanation:
# error   - 仅错误 / Errors only
# warn    - 警告和错误 / Warnings and errors
# info    - 一般信息 / General information (默认)
# debug   - 调试信息 / Debug information
# trace   - 最详细 / Most verbose (所有日志 / all logs)
```

### 6.15 常见错误代码和解决方案 / Common Error Codes and Solutions

| 错误码 / Code | 名称 / Name | 原因 / Cause | 解决方案 / Solution |
|--------------|------------|-------------|-------------------|
| 0 | AINOS_OK | 成功 / Success | — |
| -1 | AINOS_ERR_INVALID_PARAM | 无效参数 / Invalid parameter | 检查 API 参数 / Check API parameters |
| -2 | AINOS_ERR_NOT_INIT | SDK 未初始化 / SDK not initialized | 调用 `ainos_init()` 和 `ainos_connect()` |
| -3 | AINOS_ERR_MODEL_NOT_FOUND | 模型未找到 / Model not found | 检查模型文件路径 / Check model file path |
| -4 | AINOS_ERR_OUT_OF_MEMORY | 内存不足 / Out of memory | 减少模型缓存或使用量化模型 / Reduce cache or use quantized model |
| -5 | AINOS_ERR_TIMEOUT | 操作超时 / Operation timed out | 增加 `inference_timeout_secs` / Increase timeout |
| -6 | AINOS_ERR_CONNECT | 连接失败 / Connection failed | 检查守护进程是否运行 / Check if daemon is running |
| -99 | AINOS_ERR_INTERNAL | 内部错误 / Internal error | 检查日志文件 / Check log files |

---

## 附录 / Appendix

### A. 系统要求 / System Requirements

| 组件 / Component | 最低要求 / Minimum | 推荐要求 / Recommended |
|-----------------|-------------------|----------------------|
| CPU | 双核 / Dual-core | 四核或更多 / Quad-core or more |
| RAM | 2 GB | 8 GB 或更多 / 8 GB or more |
| 磁盘空间 / Disk Space | 1 GB | 10 GB (含模型 / including models) |
| 操作系统 / OS | Windows 10 / Ubuntu 20.04 / macOS 12 | Windows 11 / Ubuntu 22.04 / macOS 14 |
| Rust | 1.77 | 最新稳定版 / Latest stable |
| Python | 3.8 | 3.11+ |

### B. 相关文档 / Related Documentation

- [架构文档 / Architecture](../architecture.md)
- [开发指南 / Development Guide](development.md)
- [架构决策记录 / ADR](../adr/)
- [许可证边界 / License Boundary](../license-boundary.md)
- [API 参考 / API Reference](../api/)

### C. 快速参考卡片 / Quick Reference Card

```bash
# 启动守护进程 / Start daemon
ai-daemon -c config.toml -v

# 运行验收测试 / Run verification test
python scripts/verification_test.py

# 下载模型 / Download model
python scripts/download_model.py --known qwen2.5-0.5b

# 系统托盘 / System tray
python scripts/ainos_tray.py

# Web 面板 / Web panel
python system-services/web-panel/web_server.py

# 运行基准测试 / Run benchmark
python scripts/benchmark.py

# 查看日志 / View logs
# Windows: type D:\Ainos\logs\daemon.log
# Linux: journalctl -u ai-daemon -f
# macOS: tail -f /var/log/ainos/daemon-stdout.log
# Docker: docker logs -f ainos-daemon
```

---

> **AinosOS — AI 从云到端，从内核到应用**
>
> *Making AI an OS-level service, not just an application*
>
> 文档版本 / Document Version: 1.0.0
> 最后更新 / Last Updated: 2024-01-01