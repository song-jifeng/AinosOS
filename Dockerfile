# ============================================
# Ainos OS - 多阶段 Docker 构建
# ============================================

# ---- 第一阶段：构建 ----
FROM rust:1.77-slim-bookworm AS builder

RUN apt-get update && apt-get install -y \
    pkg-config libssl-dev cmake g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 复制依赖描述文件以利用 Docker 缓存
COPY system-services/ai-daemon/Cargo.toml system-services/ai-daemon/Cargo.lock ./system-services/ai-daemon/
RUN mkdir system-services/ai-daemon/src && echo "fn main() {}" > system-services/ai-daemon/src/main.rs

# 编译依赖（缓存层）
RUN cd system-services/ai-daemon && cargo build --release 2>/dev/null || true

# 复制完整源码并编译
COPY system-services/ai-daemon/src ./system-services/ai-daemon/src
RUN cd system-services/ai-daemon && cargo build --release

# ---- 第二阶段：运行时 ----
FROM debian:bookworm-slim

# 安装运行时依赖
RUN apt-get update && apt-get install -y \
    ca-certificates libssl3 \
    && rm -rf /var/lib/apt/lists/*

# 创建目录结构
RUN mkdir -p /var/lib/ainos/{models,data/contexts,logs} \
    /etc/ainos \
    /var/run/ainos

# 复制二进制
COPY --from=builder /build/system-services/ai-daemon/target/release/ai-daemon /usr/local/bin/ai-daemon

# 复制默认配置
COPY configs/ai-daemon.toml /etc/ainos/ai-daemon.toml

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD echo '{"type":"Status"}' | timeout 3 nc 127.0.0.1 9500 || exit 1

# 暴露端口
EXPOSE 9500

# 数据卷
VOLUME ["/var/lib/ainos/models", "/var/lib/ainos/data", "/var/lib/ainos/logs"]

# 启动
CMD ["ai-daemon", "-c", "/etc/ainos/ai-daemon.toml"]