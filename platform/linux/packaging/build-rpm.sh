#!/usr/bin/env bash
# ============================================================================
# AinosOS - Fedora/RHEL RPM Package Builder
# Copyright (C) 2024 AinosOS Developers
# SPDX-License-Identifier: GPL-2.0-only
#
# Builds an .rpm package for the AinosOS AI Daemon and supporting components.
# Designed for Fedora 38+, RHEL 9+, and derivatives.
#
# Usage:
#   ./build-rpm.sh [options]
#
# Options:
#   -h, --help              Show this help
#   -v, --version VERSION   Package version (default: 1.0.0)
#   -r, --release RELEASE   Package release number (default: 1)
#   -o, --output DIR        Output directory (default: ./dist)
#   -k, --keep-build        Keep build directory after packaging
#   -s, --sign              Sign the package with GPG
#   --no-strip              Don't strip debug symbols from binaries
#   --no-daemon             Skip building the Rust daemon
#   --dist DIST             Distribution tag (e.g. "fc38", "el9")
#
# Dependencies:
#   sudo dnf install rpm-build rpmdevtools gcc gcc-c++ cmake make \
#                    systemd-devel openssl-devel cargo rust
#
# Environment variables:
#   AINOS_SIGN_KEY          — GPG key ID for signing
#   AINOS_RPM_MACROS        — Extra RPM macros (space-separated)
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================
PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PLATFORM_DIR="$PROJECT_ROOT/platform/linux"

PACKAGE_NAME="ainos-daemon"
PACKAGE_VERSION="${AINOS_VERSION:-1.0.0}"
PACKAGE_RELEASE="${AINOS_RELEASE:-1}"
PACKAGE_DIST="${AINOS_DIST:-$(rpm --eval '%{?dist}' 2>/dev/null || echo '.fc38')}"
PACKAGE_LICENSE="GPL-2.0-only"
PACKAGE_VENDOR="AinosOS Developers"
PACKAGE_URL="https://github.com/ainos-os/ainos"
PACKAGE_SUMMARY="AinosOS AI Daemon - Native AI System Service"
PACKAGE_DESCRIPTION="The AinosOS AI Daemon provides AI inference, model lifecycle
management, context storage, and system monitoring capabilities. It supports
local GGML/ONNX inference with cloud API fallback, thermal-aware power policy
scheduling, and D-Bus integration for system-level AI services."

OUTPUT_DIR="${PWD}/dist"
KEEP_BUILD=false
SIGN_PACKAGE=false
STRIP_BINARIES=true
BUILD_DAEMON=true

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
        -r|--release) PACKAGE_RELEASE="$2"; shift 2 ;;
        -o|--output) OUTPUT_DIR="$2"; shift 2 ;;
        -k|--keep-build) KEEP_BUILD=true; shift ;;
        -s|--sign) SIGN_PACKAGE=true; shift ;;
        --no-strip) STRIP_BINARIES=false; shift ;;
        --no-daemon) BUILD_DAEMON=false; shift ;;
        --dist) PACKAGE_DIST="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ============================================================================
# Pre-flight Checks
# ============================================================================
echo "============================================="
echo "  AinosOS RPM Package Builder"
echo "  Version: ${PACKAGE_VERSION}-${PACKAGE_RELEASE}${PACKAGE_DIST}"
echo "  Root:    $PROJECT_ROOT"
echo "============================================="
echo ""

# Check required tools
for cmd in rpmbuild rpm; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: Required tool '$cmd' not found"
        echo "  Install: sudo dnf install rpm-build rpmdevtools"
        exit 1
    fi
done

# Check RPM build environment
RPM_BUILD_ROOT="${HOME}/rpmbuild"
if [ ! -d "$RPM_BUILD_ROOT" ]; then
    echo "Setting up RPM build environment..."
    rpmdev-setuptree 2>/dev/null || {
        mkdir -p "$RPM_BUILD_ROOT"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}
    }
fi

# ============================================================================
# Build Daemon Binary
# ============================================================================

if $BUILD_DAEMON; then
    echo ""
    echo "[1/3] Building AI Daemon (Rust)..."
    cd "$PROJECT_ROOT/system-services/ai-daemon"
    if command -v cargo &>/dev/null; then
        cargo build --release 2>&1 | tail -3
        echo "  Binary: target/release/ai-daemon"
    else
        echo "  [SKIP] Rust toolchain not found"
    fi
    cd "$PROJECT_ROOT"
fi

# ============================================================================
# Create Source Archive
# ============================================================================

echo ""
echo "[2/3] Creating source archive..."

BUILD_DIR=$(mktemp -d -t ainos-rpm-build-XXXXXX)
ARCHIVE_NAME="${PACKAGE_NAME}-${PACKAGE_VERSION}"
ARCHIVE_DIR="${BUILD_DIR}/${ARCHIVE_NAME}"
mkdir -p "$ARCHIVE_DIR"

# Create directory structure
mkdir -p "$ARCHIVE_DIR/usr/local/bin"
mkdir -p "$ARCHIVE_DIR/usr/lib/ainos"
mkdir -p "$ARCHIVE_DIR/etc/ainos"
mkdir -p "$ARCHIVE_DIR/etc/udev/rules.d"
mkdir -p "$ARCHIVE_DIR/etc/apparmor.d"
mkdir -p "$ARCHIVE_DIR/etc/dbus-1/system.d"
mkdir -p "$ARCHIVE_DIR/etc/selinux/ainos"
mkdir -p "$ARCHIVE_DIR/usr/lib/systemd/system"
mkdir -p "$ARCHIVE_DIR/usr/lib/sysusers.d"
mkdir -p "$ARCHIVE_DIR/usr/lib/tmpfiles.d"

# Copy binaries
if [ -f "$PROJECT_ROOT/system-services/ai-daemon/target/release/ai-daemon" ]; then
    cp "$PROJECT_ROOT/system-services/ai-daemon/target/release/ai-daemon" \
       "$ARCHIVE_DIR/usr/local/bin/ainos-daemon"
    if $STRIP_BINARIES; then
        strip "$ARCHIVE_DIR/usr/local/bin/ainos-daemon" 2>/dev/null || true
    fi
    chmod 755 "$ARCHIVE_DIR/usr/local/bin/ainos-daemon"
fi

# Copy configs
if [ -f "$PROJECT_ROOT/configs/ai-daemon.toml" ]; then
    cp "$PROJECT_ROOT/configs/ai-daemon.toml" "$ARCHIVE_DIR/etc/ainos/ai-daemon.conf"
    chmod 644 "$ARCHIVE_DIR/etc/ainos/ai-daemon.conf"
fi

# Copy platform files
cp "$PLATFORM_DIR/systemd/ainos-daemon.service" "$ARCHIVE_DIR/usr/lib/systemd/system/"
cp "$PLATFORM_DIR/systemd/ainos-daemon.sysusers" "$ARCHIVE_DIR/usr/lib/sysusers.d/ainos-daemon.conf"
cp "$PLATFORM_DIR/systemd/ainos-daemon.tmpfiles" "$ARCHIVE_DIR/usr/lib/tmpfiles.d/ainos-daemon.conf"
cp "$PLATFORM_DIR/udev/99-ainos.rules" "$ARCHIVE_DIR/etc/udev/rules.d/"
cp "$PLATFORM_DIR/apparmor/usr.local.bin.ainos-daemon" "$ARCHIVE_DIR/etc/apparmor.d/"

# D-Bus configuration
cat > "$ARCHIVE_DIR/etc/dbus-1/system.d/com.ainos.Daemon1.conf" << 'DBUSCONF'
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

# Helper scripts
cat > "$ARCHIVE_DIR/usr/local/bin/ainos-daemon-precheck" << 'SCRIPT'
#!/bin/sh
mkdir -p /var/lib/ainos/models /var/lib/ainos/data /var/lib/ainos/logs
mkdir -p /var/run/ainos/sockets /var/run/ainos/state
exit 0
SCRIPT
chmod 755 "$ARCHIVE_DIR/usr/local/bin/ainos-daemon-precheck"

cat > "$ARCHIVE_DIR/usr/local/bin/ainos-daemon-poststop" << 'SCRIPT'
#!/bin/sh
rm -f /var/run/ainos/ainos-daemon.sock
exit 0
SCRIPT
chmod 755 "$ARCHIVE_DIR/usr/local/bin/ainos-daemon-poststop"

# ============================================================================
# SELinux Policy Module
# ============================================================================

cat > "$ARCHIVE_DIR/etc/selinux/ainos/ainos-daemon.te" << 'SELINUX'
policy_module(ainos-daemon, 1.0.0)

########################################
# Type declarations
type ainos_daemon_t;
type ainos_daemon_exec_t;
init_daemon_domain(ainos_daemon_t, ainos_daemon_exec_t)

type ainos_var_lib_t;
files_type(ainos_var_lib_t)

type ainos_var_log_t;
logging_log_file(ainos_var_log_t)

type ainos_var_run_t;
files_pid_file(ainos_var_run_t)

########################################
# D-Bus integration
dbus_system_bus_client(ainos_daemon_t)
dbus_connect_system_bus(ainos_daemon_t)

########################################
# Network access
corenet_tcp_connect_all_ports(ainos_daemon_t)
corenet_tcp_bind_all_ports(ainos_daemon_t)
corenet_udp_bind_all_ports(ainos_daemon_t)

########################################
# File system access
allow ainos_daemon_t ainos_var_lib_t:dir rw_dir_perms;
allow ainos_daemon_t ainos_var_lib_t:file rw_file_perms;
manage_dirs_pattern(ainos_daemon_t, ainos_var_lib_t, ainos_var_lib_t)
manage_files_pattern(ainos_daemon_t, ainos_var_lib_t, ainos_var_lib_t)

allow ainos_daemon_t ainos_var_log_t:dir rw_dir_perms;
allow ainos_daemon_t ainos_var_log_t:file rw_file_perms;
logging_log_filetrans(ainos_daemon_t, ainos_var_log_t, dir, "ainos")
logging_log_filetrans(ainos_daemon_t, ainos_var_log_t, file, "ainos")

allow ainos_daemon_t ainos_var_run_t:dir rw_dir_perms;
allow ainos_daemon_t ainos_var_run_t:file rw_file_perms;
allow ainos_daemon_t ainos_var_run_t:sock_file rw_file_perms;
files_pid_filetrans(ainos_daemon_t, ainos_var_run_t, dir, "ainos")
files_pid_filetrans(ainos_daemon_t, ainos_var_run_t, file, "ainos")

########################################
# GPU access
dev_read_sysfs(ainos_daemon_t)
dev_rw_drm(ainos_daemon_t)

########################################
# Thermal monitoring
dev_read_sysfs(ainos_daemon_t)

########################################
# Capabilities
allow ainos_daemon_t self:capability { net_bind_service net_raw sys_nice ipc_lock };
allow ainos_daemon_t self:process { sched_nice };
SELINUX

# ============================================================================
# SPEC File
# ============================================================================

echo ""
echo "[3/3] Creating RPM SPEC file..."

cat > "$BUILD_DIR/${ARCHIVE_NAME}.spec" << SPEC
# ============================================================================
# AinosOS - RPM SPEC file for AI Daemon
# ============================================================================

%define _prefix /usr
%define _sysconfdir /etc
%define _unitdir %{_prefix}/lib/systemd/system
%define _sysusersdir %{_prefix}/lib/sysusers.d
%define _tmpfilesdir %{_prefix}/lib/tmpfiles.d
%define _udevrulesdir /etc/udev/rules.d
%define _apparmordir /etc/apparmor.d
%define _dbusconfdir /etc/dbus-1/system.d
%define _selinuxdir /etc/selinux/ainos

Name:       ${PACKAGE_NAME}
Version:    ${PACKAGE_VERSION}
Release:    ${PACKAGE_RELEASE}${PACKAGE_DIST}
Summary:    ${PACKAGE_SUMMARY}

License:    ${PACKAGE_LICENSE}
URL:        ${PACKAGE_URL}
Vendor:     ${PACKAGE_VENDOR}
Packager:   ${PACKAGE_VENDOR}

Source0:    %{name}-%{version}.tar.gz

BuildArch:  x86_64
BuildRequires: systemd-rpm-macros
BuildRequires: systemd-devel >= 249

Requires:   systemd >= 249
Requires:   dbus >= 1.12
Requires:   shadow-utils
Requires(pre):  shadow-utils
Requires(post): systemd
Requires(preun): systemd
Requires(postun): systemd

%description
${PACKAGE_DESCRIPTION}

%prep
%setup -q

%build
# Binaries are pre-built (see build-deb.sh for full build instructions)
# In a CI build, this would invoke cargo build --release
echo "Binaries pre-built"

%install
# Create directories
install -dm 0755 %{buildroot}%{_prefix}/local/bin
install -dm 0755 %{buildroot}%{_prefix}/lib/ainos
install -dm 0755 %{buildroot}%{_sysconfdir}/ainos
install -dm 0755 %{buildroot}%{_unitdir}
install -dm 0755 %{buildroot}%{_sysusersdir}
install -dm 0755 %{buildroot}%{_tmpfilesdir}
install -dm 0755 %{buildroot}%{_udevrulesdir}
install -dm 0755 %{buildroot}%{_apparmordir}
install -dm 0755 %{buildroot}%{_dbusconfdir}
install -dm 0755 %{buildroot}%{_selinuxdir}

# Install binaries
install -m 0755 usr/local/bin/ainos-daemon %{buildroot}%{_prefix}/local/bin/
install -m 0755 usr/local/bin/ainos-daemon-precheck %{buildroot}%{_prefix}/local/bin/
install -m 0755 usr/local/bin/ainos-daemon-poststop %{buildroot}%{_prefix}/local/bin/

# Install configuration
install -m 0644 etc/ainos/ai-daemon.conf %{buildroot}%{_sysconfdir}/ainos/

# Install systemd units
install -m 0644 usr/lib/systemd/system/ainos-daemon.service %{buildroot}%{_unitdir}/

# Install sysusers and tmpfiles
install -m 0644 usr/lib/sysusers.d/ainos-daemon.conf %{buildroot}%{_sysusersdir}/
install -m 0644 usr/lib/tmpfiles.d/ainos-daemon.conf %{buildroot}%{_tmpfilesdir}/

# Install udev rules
install -m 0644 etc/udev/rules.d/99-ainos.rules %{buildroot}%{_udevrulesdir}/

# Install AppArmor profile
install -m 0644 etc/apparmor.d/usr.local.bin.ainos-daemon %{buildroot}%{_apparmordir}/

# Install D-Bus configuration
install -m 0644 etc/dbus-1/system.d/com.ainos.Daemon1.conf %{buildroot}%{_dbusconfdir}/

# Install SELinux policy
install -m 0644 etc/selinux/ainos/ainos-daemon.te %{buildroot}%{_selinuxdir}/

%check
# Verify binary exists and is executable
test -x %{buildroot}%{_prefix}/local/bin/ainos-daemon

%pre
# Create ainos user and group if not present
getent group ainos >/dev/null 2>&1 || groupadd -r ainos
getent passwd ainos >/dev/null 2>&1 || \
    useradd -r -g ainos -d /var/lib/ainos -s /sbin/nologin \
    -c "AinosOS Daemon" ainos

%post
# Create directories
systemd-tmpfiles --create %{_tmpfilesdir}/ainos-daemon.conf >/dev/null 2>&1 || :

# Reload systemd
%systemd_post ainos-daemon.service

# Reload udev
udevadm control --reload-rules >/dev/null 2>&1 || :
udevadm trigger >/dev/null 2>&1 || :

# Reload SELinux policy if available
if command -v semodule >/dev/null 2>&1; then
    semodule -r ainos-daemon 2>/dev/null || :
    semodule -i %{_selinuxdir}/ainos-daemon.te 2>/dev/null || :
    restorecon -R /usr/local/bin /etc/ainos /var/lib/ainos 2>/dev/null || :
fi

%preun
%systemd_preun ainos-daemon.service

%postun
%systemd_postun_with_restart ainos-daemon.service

%files
%defattr(-,root,root,-)
%{_prefix}/local/bin/ainos-daemon
%{_prefix}/local/bin/ainos-daemon-precheck
%{_prefix}/local/bin/ainos-daemon-poststop
%dir %{_sysconfdir}/ainos
%config(noreplace) %{_sysconfdir}/ainos/ai-daemon.conf
%{_unitdir}/ainos-daemon.service
%{_sysusersdir}/ainos-daemon.conf
%{_tmpfilesdir}/ainos-daemon.conf
%{_udevrulesdir}/99-ainos.rules
%{_apparmordir}/usr.local.bin.ainos-daemon
%{_dbusconfdir}/com.ainos.Daemon1.conf
%{_selinuxdir}/ainos-daemon.te

%doc
%license COPYING

%changelog
* $(date "+%a %b %d %Y") ${PACKAGE_VENDOR} - ${PACKAGE_VERSION}-${PACKAGE_RELEASE}
- Initial RPM package release
- AI inference engine with local GGML/ONNX support
- Cloud API fallback for remote inference
- Context management with LRU caching and SQLite persistence
- Thermal-aware power policy scheduling
- D-Bus integration for system-level AI services
- cgroups v2 resource management
- udev rules for GPU and AI accelerator access
- AppArmor security profile
- systemd service with security hardening
SPEC

# ============================================================================
# Build RPM
# ============================================================================

# Create source tarball
cd "$BUILD_DIR"
tar czf "${RPM_BUILD_ROOT}/SOURCES/${ARCHIVE_NAME}.tar.gz" "${ARCHIVE_NAME}/"

# Copy SPEC file
cp "${ARCHIVE_NAME}.spec" "${RPM_BUILD_ROOT}/SPECS/"

# Build RPM
echo ""
echo "Building RPM package..."
RPM_DEFINES=()
RPM_DEFINES+=("--define" "debug_package %{nil}")
RPM_DEFINES+=("--define" "_rpmfilename %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm")

mkdir -p "$OUTPUT_DIR"
rpmbuild -bb "${RPM_DEFINES[@]}" \
    "${RPM_BUILD_ROOT}/SPECS/${ARCHIVE_NAME}.spec" 2>&1 | tee "$BUILD_DIR/rpmbuild.log"

# Copy RPM to output directory
RPM_FILE="${RPM_BUILD_ROOT}/RPMS/x86_64/${PACKAGE_NAME}-${PACKAGE_VERSION}-${PACKAGE_RELEASE}${PACKAGE_DIST}.x86_64.rpm"
if [ -f "$RPM_FILE" ]; then
    cp "$RPM_FILE" "$OUTPUT_DIR/"
    echo ""
    echo "============================================="
    echo "  Package built successfully!"
    echo "============================================="
    echo "  Package: $OUTPUT_DIR/$(basename "$RPM_FILE")"
    echo "  Size:    $(du -h "$OUTPUT_DIR/$(basename "$RPM_FILE")" | cut -f1)"
    echo "  Version: ${PACKAGE_VERSION}-${PACKAGE_RELEASE}${PACKAGE_DIST}"
    echo ""
    echo "Install:"
    echo "  sudo dnf install $OUTPUT_DIR/$(basename "$RPM_FILE")"
    echo ""
else
    echo "ERROR: RPM build failed. Check build log:"
    echo "  $BUILD_DIR/rpmbuild.log"
    tail -20 "$BUILD_DIR/rpmbuild.log"
    exit 1
fi

# Sign if requested
if $SIGN_PACKAGE; then
    SIGN_KEY="${AINOS_SIGN_KEY:-}"
    if [ -n "$SIGN_KEY" ]; then
        rpm --addsign --define "_gpg_name $SIGN_KEY" \
            "$OUTPUT_DIR/$(basename "$RPM_FILE")" 2>&1
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