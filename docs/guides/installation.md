# AinosOS 安装指南

## 概述

本文档介绍如何从源码编译安装 AinosOS，以及在各平台上的安装步骤。AinosOS 支持 Windows、Linux 和 macOS 三大主流平台。

## 系统要求

### 最低硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 4 核 x86-64/ARM64 | 8 核以上 |
| 内存 | 8 GB | 32 GB 以上 |
| 磁盘 | 10 GB 空闲空间 | 50 GB SSD |
| GPU (可选) | NVIDIA GTX 1060 6GB | NVIDIA RTX 4090 24GB |
| 网络 | 千兆以太网 | 千兆以太网 |

### 支持的操作系统

| 操作系统 | 版本 | 架构 |
|---------|------|------|
| Windows | 10/11 (21H2+) | x86-64 |
| Ubuntu | 20.04/22.04/24.04 LTS | x86-64, ARM64 |
| Debian | 11/12 | x86-64, ARM64 |
| Fedora | 38+ | x86-64 |
| macOS | 13 (Ventura)+ | ARM64 (Apple Silicon) |
| macOS | 13+ | x86-64 (Intel) |

### 软件依赖

#### 通用依赖

| 软件 | 版本 | 说明 |
|------|------|------|
| CMake | >= 3.22 | 构建系统 |
| C 编译器 | GCC >= 11 / MSVC 2022 / Clang >= 14 | 编译工具链 |
| Git | >= 2.30 | 版本控制 |
| Python | >= 3.10 | 构建脚本和 SDK |
| Ninja | >= 1.10 | 构建加速 (可选) |

#### Linux 额外依赖

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    libssl-dev \
    libcurl4-openssl-dev \
    libncurses-dev \
    libgomp1 \
    libatomic1 \
    pkg-config

# Fedora
sudo dnf install -y \
    gcc-c++ \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    openssl-devel \
    libcurl-devel \
    ncurses-devel \
    libgomp \
    libatomic \
    pkgconfig
```

#### Windows 额外依赖

```powershell
# 安装 Visual Studio 2022 或 Visual Studio Build Tools
# 确保安装了以下组件：
# - MSVC v143 - VS 2022 C++ x64/x86 build tools
# - Windows 10/11 SDK
# - CMake 工具

# 使用 Chocolatey 安装依赖
choco install -y cmake ninja python3 git

# 或使用 winget
winget install -e --id Kitware.CMake
winget install -e --id Ninja-build.Ninja
winget install -e --id Python.Python.3.12
```

#### macOS 额外依赖

```bash
# 安装 Homebrew（如未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装依赖
brew install cmake ninja python3

# 安装 Xcode Command Line Tools
xcode-select --install
```

## 从源码编译

### 1. 克隆仓库

```bash
git clone https://github.com/ainos/ainos.git
cd ainos
git checkout v2.1.0  # 使用稳定版本
git submodule update --init --recursive
```

### 2. 配置构建

```bash
mkdir build && cd build

# 基本构建（CPU 模式）
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local

# 使用 GPU 加速（CUDA）
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_CUDA=ON \
    -DCUDA_ARCHITECTURES="80;86;89" \
    -DCMAKE_INSTALL_PREFIX=/usr/local

# 使用 Vulkan 加速
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_VULKAN=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local

# 使用 Metal 加速（macOS）
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_METAL=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local

# 完整构建（所有特性）
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_CUDA=ON \
    -DAINOS_VULKAN=ON \
    -DAINOS_METAL=ON \
    -DAINOS_TESTS=ON \
    -DAINOS_BENCHMARKS=ON \
    -DAINOS_DOCS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local
```

### 3. 编译

```bash
# 使用 Ninja 编译（推荐）
ninja -j$(nproc)

# 或使用 Make
make -j$(nproc)
```

### 4. 运行测试

```bash
# 运行所有测试
ctest --output-on-failure -j$(nproc)

# 运行特定测试
ctest -R "test_inference" --output-on-failure

# 运行性能测试
ctest -R "benchmark" --output-on-failure
```

### 5. 安装

```bash
# 安装到系统
sudo ninja install  # 或 sudo make install

# 安装到指定目录
cmake --install . --prefix /opt/ainos
```

### CMake 选项参考

| 选项 | 默认值 | 说明 |
|------|--------|------|
| AINOS_CUDA | OFF | 启用 CUDA 加速 |
| AINOS_VULKAN | OFF | 启用 Vulkan 加速 |
| AINOS_METAL | OFF | 启用 Metal 加速 (macOS) |
| AINOS_TESTS | OFF | 构建测试 |
| AINOS_BENCHMARKS | OFF | 构建基准测试 |
| AINOS_DOCS | OFF | 构建文档 |
| AINOS_SHARED | ON | 构建共享库 |
| AINOS_STATIC | OFF | 构建静态库 |
| AINOS_SANITIZER | OFF | 启用地址消毒器 |
| AINOS_COVERAGE | OFF | 启用覆盖率检测 |
| AINOS_PROFILING | OFF | 启用性能分析 |
| AINOS_JEMALLOC | OFF | 使用 jemalloc 内存分配器 |
| AINOS_AVX2 | ON | 启用 AVX2 指令集 |
| AINOS_AVX512 | OFF | 启用 AVX-512 指令集 |
| AINOS_NEON | OFF | 启用 NEON 指令集 (ARM) |

## 各平台安装步骤

### Linux (Ubuntu/Debian)

#### 使用预编译包

```bash
# 添加仓库
echo "deb https://packages.ainos.com/ubuntu $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/ainos.list
wget -qO- https://packages.ainos.com/ainos.gpg | sudo apt-key add -

# 安装
sudo apt-get update
sudo apt-get install -y ainos

# 安装 GPU 支持
sudo apt-get install -y ainos-cuda    # CUDA 支持
sudo apt-get install -y ainos-vulkan  # Vulkan 支持
```

#### 从源码编译

```bash
# 安装依赖
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    ninja-build \
    python3 \
    python3-pip \
    libssl-dev \
    libcurl4-openssl-dev \
    libncurses-dev \
    libgomp1 \
    libatomic1 \
    pkg-config

# 编译安装
git clone https://github.com/ainos/ainos.git
cd ainos
git checkout v2.1.0
git submodule update --init --recursive

mkdir build && cd build
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_TESTS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local
ninja -j$(nproc)
sudo ninja install

# 配置动态库路径
sudo ldconfig
```

### Windows

#### 使用预编译安装包

1. 从 [AinosOS 发布页面](https://github.com/ainos/ainos/releases) 下载最新版安装包
2. 运行 `ainos-windows-x64-2.1.0.exe`
3. 按照安装向导完成安装
4. 安装程序会自动添加系统 PATH

#### 使用 vcpkg

```powershell
# 安装 vcpkg（如未安装）
git clone https://github.com/Microsoft/vcpkg.git
cd vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg integrate install

# 安装 AinosOS
.\vcpkg install ainos:x64-windows

# 安装 GPU 支持
.\vcpkg install ainos[cuda]:x64-windows
```

#### 使用 Chocolatey

```powershell
choco install ainos
```

#### 从源码编译（Visual Studio）

```powershell
# 安装依赖
choco install -y cmake ninja python3 git

# 克隆仓库
git clone https://github.com/ainos/ainos.git
cd ainos
git checkout v2.1.0
git submodule update --init --recursive

# 配置
mkdir build; cd build
cmake .. -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_INSTALL_PREFIX="C:/Program Files/Ainos" `
    -DAINOS_TESTS=ON

# 编译
ninja -j$(nproc)

# 安装
ninja install
```

### macOS

#### 使用 Homebrew

```bash
# 安装
brew tap ainos/ainos
brew install ainos

# 安装 GPU 支持（Metal）
brew install ainos --with-metal
```

#### 从源码编译

```bash
# 安装依赖
brew install cmake ninja python3

# 克隆仓库
git clone https://github.com/ainos/ainos.git
cd ainos
git checkout v2.1.0
git submodule update --init --recursive

# 编译
mkdir build && cd build
cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_METAL=ON \
    -DAINOS_TESTS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local
ninja -j$(sysctl -n hw.logicalcpu)
sudo ninja install
```

## Docker 部署

### 使用官方镜像

```bash
# CPU 版本
docker pull ainos/ainos:2.1.0-cpu

# CUDA 版本
docker pull ainos/ainos:2.1.0-cuda

# 运行容器
docker run -d \
    --name ainos-server \
    -p 9500:9500 \
    -v /path/to/models:/models \
    -v /path/to/config:/etc/ainos \
    ainos/ainos:2.1.0-cpu
```

### 自定义 Dockerfile

```dockerfile
FROM ubuntu:22.04 AS builder

RUN apt-get update && apt-get install -y \
    build-essential cmake ninja-build python3 \
    libssl-dev libcurl4-openssl-dev pkg-config \
    git

WORKDIR /src
RUN git clone https://github.com/ainos/ainos.git && \
    cd ainos && git checkout v2.1.0 && \
    git submodule update --init --recursive

WORKDIR /src/ainos/build
RUN cmake .. -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_TESTS=OFF && \
    ninja -j$(nproc) && \
    ninja install

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    libgomp1 libatomic1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/ainosd /usr/local/bin/
COPY --from=builder /usr/local/lib/libainos* /usr/local/lib/
RUN ldconfig

EXPOSE 9500
VOLUME ["/models", "/etc/ainos"]

ENTRYPOINT ["ainosd"]
CMD ["--config", "/etc/ainos/config.yaml"]
```

## 验证安装

### 检查版本

```bash
ainosd --version
# 预期输出: AinosOS v2.1.0
```

### 运行服务

```bash
# 启动服务
ainosd --config /etc/ainos/config.yaml

# 后台运行
ainosd --config /etc/ainos/config.yaml --daemon

# 检查状态
ainosctl status
```

### 测试连接

```bash
# 使用 Python SDK 测试
python3 -c "
from ainos import AinosClient
client = AinosClient()
client.connect()
info = client.get_system_info()
print(f'连接成功! AinosOS v{info.version}')
client.disconnect()
"
```

## 故障排除

### 编译错误

#### 1. CMake 找不到依赖

**问题**:
```
CMake Error at CMakeLists.txt:42 (find_package):
  Could not find a package configuration file provided by "OpenSSL"
```

**解决方案**:
```bash
# Linux
sudo apt-get install -y libssl-dev

# macOS
brew install openssl
export CMAKE_PREFIX_PATH="/usr/local/opt/openssl:$CMAKE_PREFIX_PATH"

# Windows
# 确保 OpenSSL 已安装且在 PATH 中
```

#### 2. CUDA 未找到

**问题**:
```
CMake Error: CUDA not found. Please install CUDA Toolkit.
```

**解决方案**:
```bash
# 安装 CUDA Toolkit 12.x
# 从 https://developer.nvidia.com/cuda-downloads 下载并安装

# 设置 CUDA 路径
export CUDA_PATH=/usr/local/cuda-12
export PATH=$CUDA_PATH/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_PATH/lib64:$LD_LIBRARY_PATH
```

#### 3. 编译内存不足

**问题**: 编译过程中因内存不足导致进程被杀死

**解决方案**:
```bash
# 减少并行编译任务数
ninja -j2

# 或使用链接时优化降级
cmake .. -DCMAKE_INTERPROCEDURAL_OPTIMIZATION=OFF
```

### 运行时错误

#### 1. 无法加载共享库

**问题**:
```
error while loading shared libraries: libainos.so: cannot open shared object file
```

**解决方案**:
```bash
# Linux
sudo ldconfig

# 或手动设置 LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# macOS
sudo update_dyld_shared_cache
```

#### 2. 端口被占用

**问题**:
```
ERROR: bind failed: Address already in use
```

**解决方案**:
```bash
# 查找占用端口的进程
sudo lsof -i :9500

# 修改默认端口
ainosd --port 9501

# 或修改配置文件
# config.yaml 中修改 daemon.port
```

#### 3. 模型加载失败

**问题**:
```
ERROR: Failed to load model: Invalid model file
```

**解决方案**:
```bash
# 检查模型文件完整性
sha256sum /path/to/model.gguf

# 确认模型文件格式支持
ainosctl inspect /path/to/model.gguf

# 检查是否有足够内存
free -h
```

#### 4. GPU 内存不足

**问题**:
```
ERROR: CUDA out of memory
```

**解决方案**:
```bash
# 使用低精度量化
ainosctl load --quantization Q4_K_M /path/to/model.gguf

# 限制 GPU 内存使用
ainosd --gpu-memory-limit 8GB

# 减少 GPU 层数
ainosctl load --gpu-layers 16 /path/to/model.gguf
```

#### 5. 权限错误

**问题**:
```
ERROR: Permission denied: /var/run/ainos.sock
```

**解决方案**:
```bash
# 确保用户有权限访问 Socket 文件
sudo usermod -a -G ainos $USER

# 或修改 Socket 路径
ainosd --socket /tmp/ainos.ipc
```

### 性能问题

#### 1. 推理速度慢

**解决方案**:
```bash
# 增加线程数
ainosctl infer --threads 8

# 使用 GPU 加速
ainosd --gpu-layers 32

# 使用更小的量化
ainosctl load --quantization Q4_K_M /path/to/model.gguf

# 启用批处理
ainosctl infer --batch-size 8
```

#### 2. 内存占用过高

**解决方案**:
```bash
# 限制上下文大小
ainosctl create-context --context-size 2048

# 使用低内存模式
ainosd --low-memory

# 定期清理缓存
ainosctl clear-cache
```

## 卸载

### Linux

```bash
# 使用 apt 卸载（如果通过包管理器安装）
sudo apt-get remove --purge ainos

# 从源码编译安装的卸载
# 进入 build 目录
cd /path/to/ainos/build
sudo ninja uninstall
# 或手动删除文件
sudo rm -rf /usr/local/bin/ainosd
sudo rm -rf /usr/local/bin/ainosctl
sudo rm -rf /usr/local/lib/libainos*
sudo rm -rf /usr/local/include/ainos
sudo rm -rf /etc/ainos
```

### Windows

```powershell
# 使用安装程序卸载
# 控制面板 -> 程序和功能 -> AinosOS -> 卸载

# 或使用 Chocolatey
choco uninstall ainos
```

### macOS

```bash
# 使用 Homebrew 卸载
brew uninstall ainos

# 手动卸载
sudo rm -rf /usr/local/bin/ainosd
sudo rm -rf /usr/local/lib/libainos*
sudo rm -rf /usr/local/include/ainos
sudo rm -rf /etc/ainos
```

## 升级指南

### 从 v1.x 升级到 v2.x

```bash
# 1. 备份配置文件
cp /etc/ainos/config.yaml /etc/ainos/config.yaml.bak

# 2. 停止旧版本服务
ainosctl stop

# 3. 安装新版本
# 请参考各平台的安装步骤

# 4. 迁移配置
# config.yaml 格式有变更，请参考配置文档迁移

# 5. 启动新版本
ainosd --config /etc/ainos/config.yaml

# 6. 验证
ainosctl status
```

### 版本兼容性

| 升级路径 | 配置文件兼容 | 模型兼容 | API 兼容 |
|---------|------------|---------|---------|
| 1.0 -> 1.1 | 是 | 是 | 是 |
| 1.1 -> 1.5 | 是 | 是 | 是 |
| 1.5 -> 2.0 | 否（需迁移） | 是 | 部分（需更新 SDK） |
| 2.0 -> 2.1 | 是 | 是 | 是 |

## 常见问题

### 1. 如何选择合适的量化类型？

| 量化类型 | 模型大小 | 质量损失 | 推荐场景 |
|---------|---------|---------|---------|
| Q4_K_M | 25% | 微小 | 通用推荐 |
| Q5_K_M | 33% | 极小 | 质量优先 |
| Q8_0 | 50% | 几乎无 | 高质量需求 |
| Q2_K | 15% | 较大 | 内存严重受限 |

### 2. 如何选择 GPU 层数？

- 8B 模型: 推荐 32 层（全部）GPU 加速
- 70B 模型: 推荐 40-60 层 GPU 加速
- 使用 `--gpu-layers -1` 自动检测最佳层数

### 3. 如何优化内存使用？

- 使用量化模型（Q4_K_M 比 Q8_0 减少 50% 内存）
- 减小上下文长度（2048 比 8192 减少 75% KV 缓存）
- 启用低内存模式（牺牲部分速度）
- 使用 mmap 加载模型（共享内存映射）

### 4. 如何配置多 GPU？

```bash
# 指定 GPU 设备
ainosd --gpu-devices 0,1

# 分配 GPU 层数
ainosctl load --gpu-layers 32 --gpu-split 16,16
```

### 5. 如何启用日志调试？

```bash
# 设置日志级别
ainosd --log-level debug

# 输出到文件
ainosd --log-file /var/log/ainos.log

# 实时查看日志
tail -f /var/log/ainos.log
```

### 6. 配置文件路径

| 平台 | 配置文件路径 | 日志文件路径 |
|------|------------|------------|
| Linux | /etc/ainos/config.yaml | /var/log/ainos/ |
| Windows | C:\ProgramData\Ainos\config.yaml | C:\ProgramData\Ainos\logs\ |
| macOS | /usr/local/etc/ainos/config.yaml | /usr/local/var/log/ainos/ |