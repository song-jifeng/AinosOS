#!/usr/bin/env bash
# ============================================================================
# AinosOS - Debian/Ubuntu Package Builder
# Copyright (C) 2024 AinosOS Developers
# SPDX-License-Identifier: GPL-2.0-only
#
# Builds a .deb package for the AinosOS AI Daemon and supporting components.
# Designed for Debian Bookworm, Ubuntu 22.04+, and derivatives.
#
# Usage:
#   ./build-deb.sh [options]
#
# Options:
#   -h, --help              Show this help
#   -v, --version VERSION   Package version (default: 1.0.0)
#   -o, --output DIR        Output directory (default: ./dist)
#   -k, --keep-build        Keep build directory after packaging
#   -s, --sign              Sign the package with GPG
#   -c, --config FILE       Custom config file to include
#   --no-strip              Don't strip debug symbols from binaries
#   --no-daemon             Skip building the Rust daemon
#   --no-kernel             Skip building kernel modules
#
# Dependencies:
#   sudo apt install build-essential devscripts debhelper dh-systemd \
#                    cmake pkg-config libssl-dev cargo rustc
#
# Environment variables:
#   DEBEMAIL, DEBFULLNAME   — Set maintainer info for the changelog
#   AINOS_SIGN_KEY          — GPG key ID for signing
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PLATFORM_DIR="$PROJECT_ROOT/platform/linux"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PACKAGE_NAME="ainos-daemon"
PACKAGE_VERSION="${AINOS_VERSION:-1.0.0}"
PACKAGE_MAINTAINER="${DEBFULLNAME:-AinosOS Developers} <${DEBEMAIL:-devel@ainos.org}>"
PACKAGE_DESCRIPTION="AinosOS AI Daemon - Native AI System Service
 The AinosOS AI Daemon provides AI inference, model lifecycle management,
 context storage, and system monitoring capabilities. It supports local
 GGML/ONNX inference with cloud API fallback, thermal-aware power policy
 scheduling, and D-Bus integration for system-level AI services."

OUTPUT_DIR="${PWD}/dist"
BUILD_DIR=""
KEEP_BUILD=false
SIGN_PACKAGE=false
CUSTOM_CONFIG=""
STRIP_BINARIES=true
BUILD_DAEMON=true
BUILD_KERNEL=true

# ============================================================================
# Parse Arguments
# ============================================================================
usage() {
    sed -n '/^# Usage:/,/^$/p' "$0" | head -n -1
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        -v|--version) PACKAGE_VERSION="$2"; shift 2 ;;
        -o|--output) OUTPUT_DIR="$2"; shift 2 ;;
        -k|--keep-build) KEEP_BUILD=true; shift ;;
        -s|--sign) SIGN_PACKAGE=true; shift ;;
        -c|--config) CUSTOM_CONFIG="$2"; shift 2 ;;
        --no-strip) STRIP_BINARIES=false; shift ;;
        --no-daemon) BUILD_DAEMON=false; shift ;;
        --no-kernel) BUILD_KERNEL=false; shift ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ============================================================================
# Pre-flight Checks
# ============================================================================
echo "============================================="
echo "  AinosOS Debian Package Builder"
echo "  Version: $PACKAGE_VERSION"
echo "  Root:    $PROJECT_ROOT"
echo "============================================="
echo ""

# Check required tools
for cmd in dpkg-deb fakeroot install; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Required tool '$cmd' not found"
        echo "  Install: sudo apt install dpkg-dev fakeroot"
        exit 1
    fi
done

# Check OS
if [ ! -f /etc/debian_version ]; then
    echo "WARNING: Not running on Debian/Ubuntu. Build may fail."
    echo "  Continue anyway? [y/N]"
    read -r response
    if [[ ! "$response" =~ ^[yY] ]]; then exit 1; fi
fi

# ============================================================================
# Build Binaries
# ============================================================================

BUILD_DIR=$(mktemp -d -t ainos-deb-build-XXXXXX)
echo "Build directory: $BUILD_DIR"

# Build AI Daemon (Rust)
if $BUILD_DAEMON; then
    echo ""
    echo "[1/4] Building AI Daemon (Rust)..."
    cd "$PROJECT_ROOT/system-services/ai-daemon"
    if command -v cargo &>/dev/null; then
        cargo build --release 2>&1 | tail -3
        echo "  Binary: target/release/ai-daemon"
    else
        echo "  [SKIP] Rust toolchain not found"
        echo "  Install: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    fi
    cd "$PROJECT_ROOT"
fi

# Build AI Runtime (C/C++)
echo ""
echo "[2/4] Building AI Runtime (C)..."
mkdir -p "$BUILD_DIR/ai-runtime"
cd "$BUILD_DIR/ai-runtime"
if command -v cmake &>/dev/null; then
    cmake "$PROJECT_ROOT/ai-runtime" \
        -DCMAKE_BUILD_TYPE=Release \
        -DAINOS_ENABLE_GGML=OFF \
        -DAINOS_BUILD_TESTS=OFF 2>&1 | tail -1
    cmake --build . -j$(nproc) 2>&1 | tail -3
    echo "  AI Runtime built"
else
    echo "  [SKIP] CMake not found"
fi
cd "$PROJECT_ROOT"

# Build Kernel Modules
if $BUILD_KERNEL; then
    echo ""
    echo "[3/4] Building Kernel Modules..."
    if [ -d "$PROJECT_ROOT/kernel" ]; then
        cd "$PROJECT_ROOT/kernel"
        if [ -f /lib/modules/$(uname -r)/build/Makefile ]; then
            make clean 2>/dev/null || true
            make -j$(nproc) 2>&1 | tail -3
            echo "  Kernel modules built"
        else
            echo "  [SKIP] Kernel headers not available"
            echo "  Install: sudo apt install linux-headers-\$(uname -r)"
        fi
        cd "$PROJECT_ROOT"
    fi
fi

echo ""
echo "[4/4] Creating package structure..."

# ============================================================================
# Package Structure
# ============================================================================

PKG_DIR="$BUILD_DIR/pkg"
mkdir -p "$PKG_DIR/DEBIAN"

# Create directory structure
mkdir -p "$PKG_DIR/usr/lib/ainos"
mkdir -p "$PKG_DIR/usr/local/bin"
mkdir -p "$PKG_DIR/etc/ainos"
mkdir -p "$PKG_DIR/etc/ainos/certs"
mkdir -p "$PKG_DIR/etc/udev/rules.d"
mkdir -p "$PKG_DIR/etc/apparmor.d"
mkdir -p "$PKG_DIR/etc/dbus-1/system.d"
mkdir -p "$PKG_DIR/lib/systemd/system"
mkdir -p "$PKG_DIR/usr/lib/sysusers.d"
mkdir -p "$PKG_DIR/usr/lib/tmpfiles.d"
mkdir -p "$PKG_DIR/usr/share/doc/ainos-daemon"
mkdir -p "$PKG_DIR/usr/share/lintian/overrides"

# ============================================================================
# Copy Binaries
# ============================================================================

# AI Daemon binary
if [ -f "$PROJECT_ROOT/system-services/ai-daemon/target/release/ai-daemon" ]; then
    cp "$PROJECT_ROOT/system-services/ai-daemon/target/release/ai-daemon" \
       "$PKG_DIR/usr/local/bin/ainos-daemon"
    if $STRIP_BINARIES; then
        strip "$PKG_DIR/usr/local/bin/ainos-daemon" 2>/dev/null || true
    fi
    chmod 755 "$PKG_DIR/usr/local/bin/ainos-daemon"
fi

# AI Runtime libraries
if [ -f "$BUILD_DIR/ai-runtime/libainos_runtime.so" ]; then
    cp "$BUILD_DIR/ai-runtime/libainos_runtime.so" "$PKG_DIR/usr/lib/ainos/"
    chmod 644 "$PKG_DIR/usr/lib/ainos/libainos_runtime.so"
fi

# Pre-check and post-stop scripts
cat > "$PKG_DIR/usr/bin/ainos-daemon-precheck" << 'SCRIPT'
#!/bin/sh
# AinosOS daemon pre-check script
# Verifies that the system meets requirements before starting the daemon
if [ ! -d /var/lib/ainos ]; then
    mkdir -p /var/lib/ainos/models /var/lib/ainos/data /var/lib/ainos/logs
fi
if [ ! -d /var/run/ainos ]; then
    mkdir -p /var/run/ainos/sockets /var/run/ainos/state
fi
exit 0
SCRIPT
chmod 755 "$PKG_DIR/usr/bin/ainos-daemon-precheck"

cat > "$PKG_DIR/usr/bin/ainos-daemon-poststop" << 'SCRIPT'
#!/bin/sh
# AinosOS daemon post-stop script
# Cleans up runtime resources after daemon stops
rm -f /var/run/ainos/ainos-daemon.sock
exit 0
SCRIPT
chmod 755 "$PKG_DIR/usr/bin/ainos-daemon-poststop"

# ============================================================================
# Copy Configuration Files
# ============================================================================

# Config file
if [ -n "$CUSTOM_CONFIG" ] && [ -f "$CUSTOM_CONFIG" ]; then
    cp "$CUSTOM_CONFIG" "$PKG_DIR/etc/ainos/ai-daemon.conf"
elif [ -f "$PROJECT_ROOT/configs/ai-daemon.toml" ]; then
    cp "$PROJECT_ROOT/configs/ai-daemon.toml" "$PKG_DIR/etc/ainos/ai-daemon.conf"
fi

# Systemd service
cp "$PLATFORM_DIR/systemd/ainos-daemon.service" "$PKG_DIR/lib/systemd/system/"
chmod 644 "$PKG_DIR/lib/systemd/system/ainos-daemon.service"

# Systemd sysusers
cp "$PLATFORM_DIR/systemd/ainos-daemon.sysusers" "$PKG_DIR/usr/lib/sysusers.d/ainos-daemon.conf"
chmod 644 "$PKG_DIR/usr/lib/sysusers.d/ainos-daemon.conf"

# Systemd tmpfiles
cp "$PLATFORM_DIR/systemd/ainos-daemon.tmpfiles" "$PKG_DIR/usr/lib/tmpfiles.d/ainos-daemon.conf"
chmod 644 "$PKG_DIR/usr/lib/tmpfiles.d/ainos-daemon.conf"

# udev rules
cp "$PLATFORM_DIR/udev/99-ainos.rules" "$PKG_DIR/etc/udev/rules.d/"
chmod 644 "$PKG_DIR/etc/udev/rules.d/99-ainos.rules"

# AppArmor profile
cp "$PLATFORM_DIR/apparmor/usr.local.bin.ainos-daemon" "$PKG_DIR/etc/apparmor.d/"
chmod 644 "$PKG_DIR/etc/apparmor.d/usr.local.bin.ainos-daemon"

# D-Bus configuration
cat > "$PKG_DIR/etc/dbus-1/system.d/com.ainos.Daemon1.conf" << 'DBUSCONF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy user="ainos">
    <allow own="com.ainos.Daemon1"/>
    <allow send_destination="com.ainos.Daemon1"/>
    <allow receive_sender="com.ainos.Daemon1"/>
  </policy>
  <policy context="default">
    <deny own="com.ainos.Daemon1"/>
    <allow send_destination="com.ainos.Daemon1"/>
    <allow receive_sender="com.ainos.Daemon1"/>
  </policy>
</busconfig>
DBUSCONF
chmod 644 "$PKG_DIR/etc/dbus-1/system.d/com.ainos.Daemon1.conf"

# ============================================================================
# Documentation
# ============================================================================

cat > "$PKG_DIR/usr/share/doc/ainos-daemon/changelog" << CHANGELOG
ainos-daemon ($PACKAGE_VERSION) stable; urgency=medium

  * Initial Debian package release
  * AI inference engine with local GGML/ONNX support
  * Cloud API fallback for remote inference
  * Context management with LRU caching and SQLite persistence
  * Thermal-aware power policy scheduling
  * D-Bus integration for system-level AI services
  * cgroups v2 resource management
  * udev rules for GPU and AI accelerator access
  * AppArmor security profile
  * systemd service with security hardening

 -- $PACKAGE_MAINTAINER  $(date -R)
CHANGELOG
gzip -9 "$PKG_DIR/usr/share/doc/ainos-daemon/changelog"

cat > "$PKG_DIR/usr/share/doc/ainos-daemon/copyright" << COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: AinosOS
Upstream-Contact: AinosOS Developers <devel@ainos.org>
Source: https://github.com/ainos-os/ainos

Files: *
Copyright: 2024 AinosOS Developers
License: GPL-2.0+
 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 2 of the License, or
 (at your option) any later version.
 .
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

Files: debian/*
Copyright: 2024 AinosOS Developers
License: GPL-2.0+
COPYRIGHT

# Lintian override
cat > "$PKG_DIR/usr/share/lintian/overrides/ainos-daemon" << 'LINTIAN'
# The daemon needs to bind to privileged ports for some configurations
ainos-daemon binary: setuid-binary usr/local/bin/ainos-daemon
# Private network access is intentional for cloud API fallback
ainos-daemon systemd-service: systemd-service-defines-protect-system-strict
LINTIAN

# ============================================================================
# Debian Control File
# ============================================================================

ARCHITECTURE=$(dpkg --print-architecture 2>/dev/null || echo "amd64")
INSTALLED_SIZE=$(du -sk "$PKG_DIR" | cut -f1)

cat > "$PKG_DIR/DEBIAN/control" << CONTROL
Package: ainos-daemon
Version: $PACKAGE_VERSION
Section: admin
Priority: optional
Architecture: $ARCHITECTURE
Installed-Size: $INSTALLED_SIZE
Maintainer: $PACKAGE_MAINTAINER
Depends: libc6 (>= 2.31), libssl3 (>= 3.0), systemd (>= 249),
         libsystemd0 (>= 249), dbus (>= 1.12), adduser
Recommends: udev, apparmor (>= 3.0), ethtool
Suggests: linux-headers, nvidia-driver, intel-opencl-icd,
          amd64-microcode, intel-microcode
Description: $PACKAGE_DESCRIPTION
CONTROL

# ============================================================================
# Maintainer Scripts
# ============================================================================

# postinst
cat > "$PKG_DIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/sh
set -e

case "$1" in
    configure)
        # Create system user (if not using sysusers)
        if ! getent passwd ainos >/dev/null 2>&1; then
            adduser --system --group --no-create-home \
                --home /var/lib/ainos \
                --gecos "AinosOS Daemon" ainos
        fi

        # Create directories
        systemd-tmpfiles --create /usr/lib/tmpfiles.d/ainos-daemon.conf || true

        # Reload systemd
        systemctl daemon-reload || true

        # Reload AppArmor
        if command -v apparmor_parser >/dev/null 2>&1; then
            apparmor_parser -r /etc/apparmor.d/usr.local.bin.ainos-daemon 2>/dev/null || true
        fi

        # Reload udev
        if command -v udevadm >/dev/null 2>&1; then
            udevadm control --reload-rules 2>/dev/null || true
            udevadm trigger 2>/dev/null || true
        fi

        echo "ainos-daemon: Installation complete."
        echo "  Start: sudo systemctl enable --now ainos-daemon"
        ;;
    abort-upgrade|abort-remove|abort-deconfigure)
        ;;
    *)
        echo "postinst called with unknown argument '$1'" >&2
        exit 1
        ;;
esac

# dh_installdeb will replace this with shell code automatically
#DEBHELPER#
exit 0
POSTINST

# prerm
cat > "$PKG_DIR/DEBIAN/prerm" << 'PRERM'
#!/bin/sh
set -e

case "$1" in
    remove|upgrade|deconfigure)
        # Stop the service if running
        if systemctl is-active --quiet ainos-daemon 2>/dev/null; then
            systemctl stop ainos-daemon || true
        fi
        ;;
    failed-upgrade)
        ;;
    *)
        echo "prerm called with unknown argument '$1'" >&2
        exit 1
        ;;
esac

#DEBHELPER#
exit 0
PRERM

# postrm
cat > "$PKG_DIR/DEBIAN/postrm" << 'POSTRM'
#!/bin/sh
set -e

case "$1" in
    remove|purge)
        # Disable service
        systemctl disable ainos-daemon 2>/dev/null || true
        systemctl daemon-reload 2>/dev/null || true

        if [ "$1" = "purge" ]; then
            # Remove data (only on purge)
            rm -rf /var/lib/ainos /var/log/ainos /var/run/ainos /var/cache/ainos
            # Remove system user
            userdel -r ainos 2>/dev/null || true
            groupdel ainos 2>/dev/null || true
        fi
        ;;
    upgrade|failed-upgrade)
        ;;
    *)
        echo "postrm called with unknown argument '$1'" >&2
        exit 1
        ;;
esac

#DEBHELPER#
exit 0
POSTRM

chmod 755 "$PKG_DIR/DEBIAN/postinst"
chmod 755 "$PKG_DIR/DEBIAN/prerm"
chmod 755 "$PKG_DIR/DEBIAN/postrm"

# ============================================================================
# Build Package
# ============================================================================

echo ""
echo "Building .deb package..."

mkdir -p "$OUTPUT_DIR"
DEB_FILE="${OUTPUT_DIR}/${PACKAGE_NAME}_${PACKAGE_VERSION}_${ARCHITECTURE}.deb"

# Use fakeroot to build the package with correct permissions
fakeroot dpkg-deb --build "$PKG_DIR" "$DEB_FILE" 2>&1

echo ""
echo "============================================="
echo "  Package built successfully!"
echo "============================================="
echo "  Package: $DEB_FILE"
echo "  Size:    $(du -h "$DEB_FILE" | cut -f1)"
echo "  Version: $PACKAGE_VERSION"
echo "  Arch:    $ARCHITECTURE"
echo ""
echo "Install:"
echo "  sudo dpkg -i $DEB_FILE"
echo "  sudo apt install -f   # install dependencies"
echo ""

# Sign package if requested
if $SIGN_PACKAGE; then
    SIGN_KEY="${AINOS_SIGN_KEY:-}"
    if [ -n "$SIGN_KEY" ]; then
        dpkg-sig -k "$SIGN_KEY" --sign builder "$DEB_FILE" 2>&1
        echo "Package signed with key: $SIGN_KEY"
    else
        echo "WARNING: No signing key specified (AINOS_SIGN_KEY)"
    fi
fi

# ============================================================================
# Cleanup
# ============================================================================

if $KEEP_BUILD; then
    echo "Build directory preserved: $BUILD_DIR"
else
    echo "Cleaning up build directory..."
    rm -rf "$BUILD_DIR"
fi

echo "Done."