#!/bin/bash
# Ainos OS 环境搭建脚本
set -euo pipefail

echo "=== Ainos OS 开发环境搭建 ==="

# 检测操作系统
OS="$(uname -s)"
echo "[*] 检测到操作系统: $OS"

# 前置检查
check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "[!] 未找到 $1，请先安装"
        return 1
    fi
    echo "[✓] $1 已安装"
}

# 检查必要工具
echo ""
echo "--- 检查开发工具 ---"
check_command gcc
check_command make
check_command python3
check_command git
check_command cmake
check_command rustc
check_command cargo

# 检查 Linux 内核头文件
echo ""
echo "--- 检查内核头文件 ---"
if [ -d "/lib/modules/$(uname -r)/build" ]; then
    echo "[✓] 内核头文件已安装 (版本: $(uname -r))"
else
    echo "[!] 内核头文件未安装，请安装:"
    echo "    Ubuntu/Debian: sudo apt install linux-headers-\$(uname -r)"
    echo "    Fedora: sudo dnf install kernel-devel"
    echo "    Arch: sudo pacman -S linux-headers"
fi

# 确认项目目录
echo ""
echo "--- 项目目录 ---"
PROJECT_ROOT="D:/Ainos"
if [ -d "$PROJECT_ROOT" ]; then
    echo "[✓] 项目根目录: $PROJECT_ROOT"
    echo "    子目录:"
    for d in docs kernel ai-runtime system-services drivers userland scripts configs; do
        [ -d "$PROJECT_ROOT/$d" ] && echo "    - $d" || echo "    - $d [缺失]"
    done
else
    echo "[!] 项目根目录不存在，请确认路径"
fi

# 检查 Rust 工具链
echo ""
echo "--- Rust 工具链 ---"
if command -v rustc &>/dev/null; then
    echo "[✓] Rust 版本: $(rustc --version)"
    echo "[✓] Cargo 版本: $(cargo --version)"

    # 检查是否安装了必要组件
    rustup component list --installed 2>/dev/null | grep -q "rust-src" && \
        echo "[✓] rust-src 组件已安装" || \
        echo "[!] rust-src 组件未安装 (rustup component add rust-src)"

    # 检查目标
    rustup target list --installed 2>/dev/null | grep -q "x86_64-unknown-linux-gnu" && \
        echo "[✓] x86_64-unknown-linux-gnu 目标已安装" || \
        echo "[!] x86_64-unknown-linux-gnu 目标未安装"
fi

# 检查 Python 包
echo ""
echo "--- Python 依赖 ---"
if command -v python3 &>/dev/null; then
    python3 -c "import requests" 2>/dev/null && \
        echo "[✓] requests 已安装" || \
        echo "[!] requests 未安装 (pip install requests)"
    python3 -c "import numpy" 2>/dev/null && \
        echo "[✓] numpy 已安装" || \
        echo "[!] numpy 未安装 (pip install numpy)"
fi

# 检查 Weelink API
echo ""
echo "--- Weelink AI 平台 ---"
if [ -f "$PROJECT_ROOT/weelink-agent/orchestrator.py" ]; then
    echo "[✓] 多智能体协调器已就绪"
    echo "    可用 AI 助手:"
    python3 "$PROJECT_ROOT/weelink-agent/orchestrator.py" --list 2>/dev/null || echo "    (运行 python3 orchestrator.py --list 查看)"
else
    echo "[!] 多智能体协调器未找到"
fi

echo ""
echo "=== 环境检查完成 ==="
echo ""
echo "下一步:"
echo "  1. cd D:/Ainos && python3 weelink-agent/orchestrator.py --collaborate \"设计并实施...\""
echo "  2. 查看 docs/ 目录了解架构设计"
echo "  3. 进入 kernel/ 目录开始内核模块开发"
echo ""