#!/usr/bin/env bash
# Ainos OS - 一键安装脚本
set -e

echo "============================================"
echo "  Ainos OS - 一键安装"
echo "============================================"
echo ""

AINOS_HOME="$(cd "$(dirname "$0")/.." && pwd)"

# 检测操作系统
OS="$(uname -s)"
case "$OS" in
    Linux*)   OS="linux";;
    Darwin*)  OS="macos";;
    *)        echo "不支持的系统: $OS"; exit 1;;
esac
echo "系统: $OS"

# 步骤 1: 检查依赖
echo ""
echo "[1/5] 检查依赖..."

# Rust
if ! command -v rustc &>/dev/null; then
    echo "  安装 Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
fi
echo "  Rust: $(rustc --version)"

# CMake
if ! command -v cmake &>/dev/null; then
    echo "  安装 CMake..."
    if [ "$OS" = "linux" ]; then
        sudo apt-get update && sudo apt-get install -y cmake g++ pkg-config libssl-dev
    elif [ "$OS" = "macos" ]; then
        brew install cmake
    fi
fi
echo "  CMake: $(cmake --version | head -1)"

# Python
if ! command -v python3 &>/dev/null; then
    echo "  安装 Python..."
    if [ "$OS" = "linux" ]; then
        sudo apt-get install -y python3 python3-pip
    elif [ "$OS" = "macos" ]; then
        brew install python3
    fi
fi
echo "  Python: $(python3 --version)"

# 步骤 2: 创建目录
echo ""
echo "[2/5] 创建目录结构..."
mkdir -p "$AINOS_HOME"/{models,data/contexts,logs}
echo "  OK"

# 步骤 3: 编译守护进程
echo ""
echo "[3/5] 编译 ai-daemon..."
cd "$AINOS_HOME/system-services/ai-daemon"
cargo build --release 2>&1 | tail -3
echo "  OK"

# 步骤 4: 安装 systemd 服务 (Linux)
echo ""
echo "[4/5] 安装系统服务..."
if [ "$OS" = "linux" ]; then
    cat > /tmp/ai-daemon.service << EOF
[Unit]
Description=Ainos OS AI Daemon
After=network.target

[Service]
Type=simple
ExecStart=$AINOS_HOME/system-services/ai-daemon/target/release/ai-daemon -c $AINOS_HOME/configs/ai-daemon.toml
WorkingDirectory=$AINOS_HOME
Restart=on-failure
RestartSec=5
Environment=RUST_LOG=info,ainos=debug
Environment=AINOS_HOME=$AINOS_HOME

[Install]
WantedBy=multi-user.target
EOF
    sudo mv /tmp/ai-daemon.service /etc/systemd/system/ai-daemon.service
    sudo systemctl daemon-reload
    echo "  服务已安装: ai-daemon"
    echo "  启动: sudo systemctl start ai-daemon"
    echo "  开机自启: sudo systemctl enable ai-daemon"
fi
echo "  OK"

# 步骤 5: 完成
echo ""
echo "[5/5] 安装完成！"
echo ""
echo "============================================"
echo "  Ainos OS 安装成功！"
echo "============================================"
echo ""
echo "  启动守护进程:"
echo "    cd $AINOS_HOME/system-services/ai-daemon"
echo "    ./target/release/ai-daemon -c $AINOS_HOME/configs/ai-daemon.toml -v"
echo ""
if [ "$OS" = "linux" ]; then
echo "    sudo systemctl start ai-daemon"
echo "    sudo systemctl enable ai-daemon"
echo ""
fi
echo "  运行验收测试:"
echo "    python3 $AINOS_HOME/scripts/verification_test.py"
echo ""
echo "  运行基准测试:"
echo "    python3 $AINOS_HOME/scripts/benchmark.py"
echo ""
echo "  下载模型:"
echo "    python3 $AINOS_HOME/scripts/download_model.py --list"
echo ""
echo "  Web 管理面板:"
echo "    python3 $AINOS_HOME/system-services/web-panel/web_server.py"
echo ""
echo "  运行全部测试:"
echo "    bash $AINOS_HOME/scripts/run_tests.sh"
echo ""