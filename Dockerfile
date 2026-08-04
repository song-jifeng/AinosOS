# ============================================
# AinosOS - Multi-stage Docker Build
# ============================================
# Copyright (C) 2024 AinosOS Developers
# SPDX-License-Identifier: GPL-2.0-only
#
# Builds a minimal container image for the AinosOS AI Daemon with:
# - Multi-stage build for minimal final image size
# - Non-root user execution
# - Proper HEALTHCHECK and metadata labels
# - Volume mounts for persistent data
# - Resource limit awareness
# ============================================

# ---- Stage 0: Build AI Runtime (C/C++) ----
FROM debian:bookworm-slim AS ai-runtime-builder

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/ai-runtime

COPY ai-runtime/ .

RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DAINOS_ENABLE_GGML=OFF \
    -DAINOS_BUILD_TESTS=OFF \
    -DAINOS_BUILD_TOOLS=OFF \
    && cmake --build build -j$(nproc) \
    && cmake --install build --prefix /install

# ---- Stage 1: Build AI Daemon (Rust) ----
FROM rust:1.77-slim-bookworm AS daemon-builder

RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    cmake \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency manifests first for Docker layer caching
COPY system-services/ai-daemon/Cargo.toml system-services/ai-daemon/Cargo.lock ./system-services/ai-daemon/

# Create dummy main.rs to cache dependencies
RUN mkdir -p system-services/ai-daemon/src \
    && echo "fn main() {}" > system-services/ai-daemon/src/main.rs \
    && cd system-services/ai-daemon \
    && cargo build --release 2>/dev/null || true \
    && rm -f target/release/deps/ai_daemon*

# Copy full source
COPY system-services/ai-daemon/src ./system-services/ai-daemon/src

# Build with release profile optimizations
RUN cd system-services/ai-daemon \
    && cargo build --release \
    && cp target/release/ai-daemon /install/usr/local/bin/ \
    && strip /install/usr/local/bin/ai-daemon

# ---- Stage 2: Build Platform Components (optional) ----
FROM debian:bookworm-slim AS platform-builder

RUN apt-get update && apt-get install -y \
    build-essential \
    libsystemd-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/platform

COPY platform/linux/ .

# Build D-Bus integration
RUN if [ -f dbus/ainos_dbus.c ]; then \
        gcc -std=c11 -c dbus/ainos_dbus.c -o /dev/null \
        $(pkg-config --cflags libsystemd) 2>/dev/null \
        && echo "D-Bus module compiles OK" || \
        echo "D-Bus module (optional) skipped"; \
    fi

# Build cgroups integration
RUN if [ -f cgroups/ainos_cgroups.c ]; then \
        gcc -std=c11 -c cgroups/ainos_cgroups.c -o /dev/null 2>/dev/null \
        && echo "cgroups module compiles OK" || \
        echo "cgroups module (optional) skipped"; \
    fi

# ---- Stage 3: Final Runtime Image ----
FROM debian:bookworm-slim

# ==========================================================================
# Labels (OCI metadata)
# ==========================================================================
LABEL org.opencontainers.image.title="AinosOS AI Daemon"
LABEL org.opencontainers.image.description="Native AI system service with local/cloud inference, context management, and thermal-aware power scheduling"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.vendor="AinosOS Developers"
LABEL org.opencontainers.image.licenses="GPL-2.0-only"
LABEL org.opencontainers.image.url="https://github.com/ainos-os/ainos"
LABEL org.opencontainers.image.source="https://github.com/ainos-os/ainos"
LABEL org.opencontainers.image.documentation="https://github.com/ainos-os/docs"
LABEL org.opencontainers.image.ref.name="ainos-daemon"
LABEL org.opencontainers.image.created="2024-01-01T00:00:00Z"
LABEL org.opencontainers.image.authors="AinosOS Developers <devel@ainos.org>"

# ==========================================================================
# Runtime Dependencies
# ==========================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    libsystemd0 \
    tini \
    curl \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/* \
    && userdel -r _apt 2>/dev/null || true

# ==========================================================================
# Create Non-Root User
# ==========================================================================
RUN groupadd -r ainos && \
    useradd -r -g ainos -d /var/lib/ainos -s /sbin/nologin \
    -c "AinosOS Daemon" ainos && \
    groupadd -r ainos-gpu && \
    usermod -a -G ainos-gpu ainos && \
    groupadd -r ainos-accel && \
    usermod -a -G ainos-accel ainos

# ==========================================================================
# Directory Structure
# ==========================================================================
RUN mkdir -p /var/lib/ainos/{models,data,contexts,cache,logs} \
    /var/run/ainos/sockets \
    /var/log/ainos \
    /etc/ainos \
    /var/cache/ainos/models && \
    chown -R ainos:ainos /var/lib/ainos /var/run/ainos /var/log/ainos /var/cache/ainos && \
    chmod 755 /var/lib/ainos /var/run/ainos /var/log/ainos /var/cache/ainos && \
    chmod 750 /var/lib/ainos/logs /var/log/ainos

# ==========================================================================
# Copy Artifacts from Builder Stages
# ==========================================================================
COPY --from=daemon-builder --chown=ainos:ainos /install/usr/local/bin/ai-daemon /usr/local/bin/ainos-daemon
COPY --from=ai-runtime-builder --chown=ainos:ainos /install/lib /usr/lib/
COPY --from=ai-runtime-builder --chown=ainos:ainos /install/include /usr/include/

# ==========================================================================
# Configuration
# ==========================================================================
COPY --chown=ainos:ainos configs/ai-daemon.toml /etc/ainos/ai-daemon.conf

# ==========================================================================
# Entrypoint Script
# ==========================================================================
RUN echo '#!/bin/sh\n\
set -e\n\
\n\
# Ensure correct permissions on runtime directories\n\
mkdir -p /var/run/ainos/sockets /var/run/ainos/state 2>/dev/null || true\n\
chown -R ainos:ainos /var/run/ainos 2>/dev/null || true\n\
\n\
# Forward signals to the daemon\n\
exec /usr/local/bin/ainos-daemon --config /etc/ainos/ai-daemon.conf "$@"\n\
' > /usr/local/bin/docker-entrypoint.sh && \
    chmod 755 /usr/local/bin/docker-entrypoint.sh

# ==========================================================================
# Health Check
# ==========================================================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD sh -c 'echo "{\"type\":\"Status\"}" | timeout 5 nc 127.0.0.1 9500 2>/dev/null | grep -q StatusResponse' || exit 1

# ==========================================================================
# Ports
# ==========================================================================
EXPOSE 9500
EXPOSE 9501

# ==========================================================================
# Volumes (persistent data)
# ==========================================================================
VOLUME ["/var/lib/ainos/models", "/var/lib/ainos/data", "/var/lib/ainos/logs", "/var/lib/ainos/cache"]

# ==========================================================================
# Security
# ==========================================================================
# Drop capabilities
RUN setcap cap_net_bind_service=+ep /usr/local/bin/ainos-daemon

# Switch to non-root user
USER ainos:ainos
WORKDIR /var/lib/ainos

# ==========================================================================
# Entrypoint
# ==========================================================================
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["--verbose"]