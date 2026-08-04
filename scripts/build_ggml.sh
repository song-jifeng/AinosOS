#!/bin/bash
# Ainos OS - Build GGML with Rust FFI bindings
# 构建 GGML 库并生成 Rust FFI 绑定
# 用法: ./build_ggml.sh [--bindgen] [--clean]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AI_RUNTIME_DIR="$PROJECT_ROOT/ai-runtime"
DAEMON_DIR="$PROJECT_ROOT/system-services/ai-daemon"
VENDOR_DIR="$DAEMON_DIR/vendor"
BUILD_DIR="$PROJECT_ROOT/build/ggml"

GGML_REPO="https://github.com/ggml-org/ggml.git"
GGML_TAG="master"  # 或固定版本如 b1234
GGML_SRC_DIR="$PROJECT_ROOT/vendor/ggml"

echo "============================================"
echo " Ainos OS - GGML Build Script"
echo "============================================"
echo "项目根目录: $PROJECT_ROOT"
echo "GGML 源码:  $GGML_SRC_DIR"
echo "构建目录:   $BUILD_DIR"
echo "Vendor 输出: $VENDOR_DIR"
echo ""

# 解析参数
USE_BINDGEN=false
CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --bindgen) USE_BINDGEN=true ;;
        --clean) CLEAN=true ;;
    esac
done

# 清理
if [ "$CLEAN" = true ]; then
    echo "[清理] 删除构建产物..."
    rm -rf "$BUILD_DIR"
    rm -rf "$VENDOR_DIR"
    echo "  完成"
    exit 0
fi

# Step 1: 克隆/更新 GGML 源码
if [ ! -d "$GGML_SRC_DIR" ]; then
    echo "[1/5] 克隆 GGML 仓库..."
    mkdir -p "$(dirname "$GGML_SRC_DIR")"
    git clone --depth 1 --branch "$GGML_TAG" "$GGML_REPO" "$GGML_SRC_DIR"
    echo "  GGML 克隆完成"
else
    echo "[1/5] GGML 源码已存在，更新..."
    cd "$GGML_SRC_DIR"
    git fetch --depth 1 origin "$GGML_TAG" 2>/dev/null || true
    git checkout "$GGML_TAG" 2>/dev/null || true
    cd "$PROJECT_ROOT"
    echo "  GGML 已更新"
fi

# Step 2: 构建 GGML 库
echo "[2/5] 构建 GGML 库..."
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

cmake "$GGML_SRC_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_BUILD_TESTS=OFF \
    -DGGML_BUILD_EXAMPLES=OFF \
    -DGGML_BUILD_BENCHMARKS=OFF \
    -DBUILD_SHARED_LIBS=ON \
    -DGGML_NATIVE=OFF \
    -DGGML_AVX=ON \
    -DGGML_AVX2=ON \
    -DGGML_F16C=ON

cmake --build . -j$(nproc) 2>&1 | tail -5

echo "  GGML 构建完成"

# Step 3: 构建 Ainos AI Runtime（含 FFI 包装）
echo "[3/5] 构建 Ainos AI Runtime..."
mkdir -p "$BUILD_DIR/ainos-runtime"
cd "$BUILD_DIR/ainos-runtime"

cmake "$AI_RUNTIME_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_ENABLE_GGML=ON \
    -DAINOS_BUILD_TESTS=OFF \
    -DAINOS_BUILD_TOOLS=OFF \
    -DCMAKE_PREFIX_PATH="$BUILD_DIR"

cmake --build . -j$(nproc) 2>&1 | tail -5

echo "  Ainos AI Runtime 构建完成"

# Step 4: 复制库文件到 vendor 目录
echo "[4/5] 复制库文件到 vendor..."
mkdir -p "$VENDOR_DIR/lib"
mkdir -p "$VENDOR_DIR/include"

# 复制 GGML 库
if [ "$(uname)" = "Linux" ]; then
    cp "$BUILD_DIR/src/libggml.so" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/ggml-engine/libggml_engine.so" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/model-manager/libmodel_manager.so" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/power-policy/libpower_policy.so" "$VENDOR_DIR/lib/" 2>/dev/null || true
elif [ "$(uname)" = "Darwin" ]; then
    cp "$BUILD_DIR/src/libggml.dylib" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/ggml-engine/libggml_engine.dylib" "$VENDOR_DIR/lib/" 2>/dev/null || true
else
    # Windows (MSYS2/MinGW)
    cp "$BUILD_DIR/src/Release/ggml.dll" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/src/Release/ggml.lib" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/ggml-engine/Release/ggml_engine.dll" "$VENDOR_DIR/lib/" 2>/dev/null || true
    cp "$BUILD_DIR/ainos-runtime/ggml-engine/Release/ggml_engine.lib" "$VENDOR_DIR/lib/" 2>/dev/null || true
fi

# 复制头文件
cp -r "$GGML_SRC_DIR/include/ggml" "$VENDOR_DIR/include/" 2>/dev/null || true
cp "$AI_RUNTIME_DIR/include/ainos/ai_runtime_ffi.h" "$VENDOR_DIR/include/" 2>/dev/null || true

echo "  库文件已复制到 $VENDOR_DIR"

# Step 5: 生成 Rust FFI 绑定（可选，需 bindgen）
if [ "$USE_BINDGEN" = true ]; then
    echo "[5/5] 生成 Rust FFI 绑定..."
    BINDINGS_DIR="$DAEMON_DIR/src/ffi"
    mkdir -p "$BINDINGS_DIR"

    # 使用 bindgen 生成 GGML 绑定
    if command -v bindgen &>/dev/null || cargo install --list 2>/dev/null | grep -q bindgen; then
        echo "  生成 ggml 绑定..."
        bindgen "$GGML_SRC_DIR/include/ggml/ggml.h" \
            --allowlist-function "ggml_.*" \
            --allowlist-type "ggml_.*" \
            --allowlist-var "GGML_.*" \
            -o "$BINDINGS_DIR/ggml_bindings.rs" \
            -- -I"$GGML_SRC_DIR/include"

        echo "  生成 gguf 绑定..."
        bindgen "$GGML_SRC_DIR/include/ggml/gguf.h" \
            --allowlist-function "gguf_.*" \
            --allowlist-type "gguf_.*" \
            -o "$BINDINGS_DIR/gguf_bindings.rs" \
            -- -I"$GGML_SRC_DIR/include"

        echo "  FFI 绑定生成完成: $BINDINGS_DIR"
    else
        echo "  [跳过] bindgen 未安装，使用手动 FFI 定义"
        echo "  安装: cargo install bindgen-cli"
    fi
else
    echo "[5/5] 跳过 bindgen (使用 --bindgen 启用)"
fi

# 创建 Cargo 链接配置
echo ""
echo "============================================"
echo " 构建完成!"
echo "============================================"
echo ""
echo "下一步:"
echo "  1. 确认 vendor 目录包含库文件: ls -la $VENDOR_DIR/lib/"
echo "  2. 设置 cargo 链接路径:"
echo "     Windows: set LIB=%LIB%;$VENDOR_DIR/lib"
echo "     Linux:   export LD_LIBRARY_PATH=\$LD_LIBRARY_PATH:$VENDOR_DIR/lib"
echo "  3. 构建 Rust daemon: cd $DAEMON_DIR && cargo build --features ggml"
echo "  4. 运行测试:  cd $DAEMON_DIR && cargo test --features ggml"