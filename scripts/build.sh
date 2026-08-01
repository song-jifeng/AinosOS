#!/bin/bash
# Ainos OS 完整构建脚本
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/build"
AI_RUNTIME_DIR="$PROJECT_ROOT/ai-runtime"
SYSTEM_SERVICES_DIR="$PROJECT_ROOT/system-services"
KERNEL_DIR="$PROJECT_ROOT/kernel"
USERLAND_DIR="$PROJECT_ROOT/userland"

echo "============================================"
echo " Ainos OS 构建系统"
echo "============================================"
echo "项目根目录: $PROJECT_ROOT"
echo "构建目录:   $BUILD_DIR"
echo ""

# 解析参数
ACTION="${1:-all}"

build_kernel() {
    echo "[1/4] 构建 AI 内核模块..."
    cd "$KERNEL_DIR"
    if [ -f /lib/modules/$(uname -r)/build/Makefile ]; then
        make clean 2>/dev/null || true
        make -j$(nproc) 2>&1 | tail -5
        echo "  内核模块构建完成:"
        ls -lh *.ko 2>/dev/null || echo "  (未构建，需要内核头文件)"
    else
        echo "  [跳过] 需要 Linux 内核头文件"
        echo "  Ubuntu: sudo apt install linux-headers-\$(uname -r)"
    fi
    cd "$PROJECT_ROOT"
}

build_ai_runtime() {
    echo "[2/4] 构建 AI Runtime..."
    mkdir -p "$BUILD_DIR/ai-runtime"
    cd "$BUILD_DIR/ai-runtime"
    cmake "$AI_RUNTIME_DIR" -DCMAKE_BUILD_TYPE=Release \
        -DAINOS_ENABLE_GGML=OFF \
        -DAINOS_BUILD_TESTS=OFF
    cmake --build . -j$(nproc) 2>&1 | tail -3
    echo "  AI Runtime 构建完成"
    cd "$PROJECT_ROOT"
}

build_system_services() {
    echo "[3/4] 构建系统服务 (Rust)..."
    cd "$SYSTEM_SERVICES_DIR/ai-daemon"
    if command -v cargo &>/dev/null; then
        cargo build --release 2>&1 | tail -3
        echo "  ai-daemon 构建完成: target/release/ai-daemon"
    else
        echo "  [跳过] 需要 Rust 工具链"
    fi
    cd "$PROJECT_ROOT"
}

build_sdk() {
    echo "[4/4] 构建 AI SDK..."
    cd "$USERLAND_DIR/sdk"
    make clean 2>/dev/null || true
    make -j$(nproc) 2>&1
    echo "  SDK 构建完成:"
    ls -lh libainos.* 2>/dev/null
    cd "$PROJECT_ROOT"
}

case "$ACTION" in
    all)
        build_kernel
        build_ai_runtime
        build_system_services
        build_sdk
        ;;
    kernel)
        build_kernel
        ;;
    runtime)
        build_ai_runtime
        ;;
    daemon)
        build_system_services
        ;;
    sdk)
        build_sdk
        ;;
    clean)
        echo "清理构建产物..."
        rm -rf "$BUILD_DIR"
        cd "$KERNEL_DIR" && make clean 2>/dev/null || true
        cd "$USERLAND_DIR/sdk" && make clean 2>/dev/null || true
        echo "清理完成"
        ;;
    *)
        echo "用法: $0 {all|kernel|runtime|daemon|sdk|clean}"
        exit 1
        ;;
esac

echo ""
echo "============================================"
echo " 构建完成!"
echo "============================================"