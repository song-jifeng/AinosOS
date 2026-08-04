#!/bin/bash
# ============================================================================
# Ainos OS - macOS Installer Script
# ============================================================================
#
# This script installs the Ainos AI daemon and its supporting services on macOS.
# It handles:
#   - Copying the daemon binary to /usr/local/lib/ainos/
#   - Installing and loading the launchd plist
#   - Setting up log rotation via newsyslog
#   - Installing XPC services
#   - Configuring the firewall (socketfilterfw)
#   - Setting up the Ainos data directories
#   - Code signing verification
#
# Usage:
#   sudo ./install.sh                    # Full installation
#   sudo ./install.sh --uninstall        # Remove all Ainos components
#   sudo ./install.sh --upgrade          # Upgrade existing installation
#   sudo ./install.sh --status           # Check installation status
#   sudo ./install.sh --help             # Show this help message
#
# Requirements:
#   - macOS 11.0 (Big Sur) or later
#   - Root privileges (sudo)
#   - Xcode Command Line Tools (for building from source)
#
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Version
VERSION="1.0.0"

# Paths
AINOS_PREFIX="/usr/local/lib/ainos"
AINOS_BIN_DIR="${AINOS_PREFIX}/bin"
AINOS_LIB_DIR="${AINOS_PREFIX}/lib"
AINOS_XPC_DIR="${AINOS_PREFIX}/xpc"
AINOS_MODELS_DIR="${AINOS_PREFIX}/models"
AINOS_CONFIG_DIR="/usr/local/etc/ainos"
AINOS_LOG_DIR="/var/log/ainos"
AINOS_RUN_DIR="/var/run/ainos"
AINOS_SPOOL_DIR="/var/spool/ainos"
AINOS_DB_DIR="/var/db/ainos"
LAUNCHD_PLIST="/Library/LaunchDaemons/com.ainos.daemon.plist"
NEWSYSLOG_CONF="/etc/newsyslog.d/ainos.conf"
FIREWALL_RULE_NAME="com.ainos.daemon"

# Daemon binary locations
DAEMON_BINARY="ai-daemon"
XPC_SERVICE_NAME="com.ainos.daemon.xpc"
XPC_SERVICE_BUNDLE="${AINOS_XPC_DIR}/${XPC_SERVICE_NAME}.xpc"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Utility Functions
# ============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)."
        exit 1
    fi
}

check_macos() {
    if [[ "$(uname)" != "Darwin" ]]; then
        log_error "This script is for macOS only."
        exit 1
    fi

    local os_version=$(sw_vers -productVersion)
    local major_version=$(echo "$os_version" | cut -d. -f1)

    if [[ "$major_version" -lt 11 ]]; then
        log_error "macOS 11.0 (Big Sur) or later is required. Current: $os_version"
        exit 1
    fi

    log_info "macOS $os_version detected"
}

# ============================================================================
# Directory Setup
# ============================================================================

setup_directories() {
    log_step "Setting up Ainos directories..."

    local dirs=(
        "$AINOS_PREFIX"
        "$AINOS_BIN_DIR"
        "$AINOS_LIB_DIR"
        "$AINOS_XPC_DIR"
        "$AINOS_MODELS_DIR"
        "$AINOS_CONFIG_DIR"
        "$AINOS_LOG_DIR"
        "$AINOS_RUN_DIR"
        "$AINOS_SPOOL_DIR"
        "$AINOS_DB_DIR"
        "$AINOS_DB_DIR/pending"
    )

    for dir in "${dirs[@]}"; do
        mkdir -p "$dir"
        log_info "Created directory: $dir"
    done

    # Set proper permissions
    chmod 755 "$AINOS_PREFIX"
    chmod 755 "$AINOS_BIN_DIR"
    chmod 755 "$AINOS_LIB_DIR"
    chmod 755 "$AINOS_XPC_DIR"
    chmod 755 "$AINOS_MODELS_DIR"
    chmod 755 "$AINOS_CONFIG_DIR"
    chmod 755 "$AINOS_LOG_DIR"
    chmod 755 "$AINOS_RUN_DIR"
    chmod 755 "$AINOS_SPOOL_DIR"
    chmod 755 "$AINOS_DB_DIR"

    log_info "Directory permissions set"
}

# ============================================================================
# Daemon Binary Installation
# ============================================================================

install_daemon_binary() {
    log_step "Installing Ainos daemon binary..."

    local source_binary=""

    # Look for the daemon binary in several locations
    local search_paths=(
        "./ai-daemon"
        "./target/release/ai-daemon"
        "./target/debug/ai-daemon"
        "../target/release/ai-daemon"
        "../target/debug/ai-daemon"
        "/usr/local/bin/ai-daemon"
    )

    for path in "${search_paths[@]}"; do
        if [[ -f "$path" && -x "$path" ]]; then
            source_binary="$path"
            break
        fi
    done

    if [[ -z "$source_binary" ]]; then
        log_warn "Daemon binary not found. Attempting to build from source..."

        # Check if cargo is available
        if command -v cargo &> /dev/null; then
            local project_dir=""
            # Try to find the project root
            if [[ -f "Cargo.toml" ]]; then
                project_dir="."
            elif [[ -f "../Cargo.toml" ]]; then
                project_dir=".."
            elif [[ -f "../../system-services/ai-daemon/Cargo.toml" ]]; then
                project_dir="../../system-services/ai-daemon"
            fi

            if [[ -n "$project_dir" ]]; then
                log_info "Building daemon from source in $project_dir..."
                (cd "$project_dir" && cargo build --release)
                source_binary="${project_dir}/target/release/ai-daemon"
            else
                log_error "Could not find Cargo.toml to build from source."
                log_error "Build the daemon manually and re-run this script."
                return 1
            fi
        else
            log_error "Rust/Cargo not found. Install Rust or build the daemon manually."
            return 1
        fi
    fi

    # Verify the binary
    if [[ ! -f "$source_binary" ]]; then
        log_error "Daemon binary not found at: $source_binary"
        return 1
    fi

    # Check if it's a universal binary (support both Intel and Apple Silicon)
    local archs=$(lipo -info "$source_binary" 2>/dev/null | grep -o "x86_64\|arm64" | wc -l)
    if [[ "$archs" -eq 0 ]]; then
        log_warn "Binary is not a universal binary (single architecture only)."
        log_warn "Consider building with: cargo build --release --target=x86_64-apple-darwin --target=aarch64-apple-darwin"
    else
        log_info "Universal binary detected: supports both Intel and Apple Silicon"
    fi

    # Copy the binary
    cp "$source_binary" "${AINOS_BIN_DIR}/ai-daemon"
    chmod 755 "${AINOS_BIN_DIR}/ai-daemon"
    chown root:wheel "${AINOS_BIN_DIR}/ai-daemon"

    log_info "Daemon binary installed: ${AINOS_BIN_DIR}/ai-daemon"
}

# ============================================================================
# XPC Service Installation
# ============================================================================

install_xpc_service() {
    log_step "Installing XPC service..."

    local xpc_source=""

    # Look for the XPC service bundle
    local search_paths=(
        "./com.ainos.daemon.xpc"
        "./build/com.ainos.daemon.xpc"
        "../build/com.ainos.daemon.xpc"
        "./build/Release/com.ainos.daemon.xpc"
    )

    for path in "${search_paths[@]}"; do
        if [[ -d "$path" ]]; then
            xpc_source="$path"
            break
        fi
    done

    if [[ -z "$xpc_source" ]]; then
        log_warn "XPC service bundle not found. Building from source..."

        if command -v clang &> /dev/null; then
            local xpc_source_file=""
            local search_files=(
                "./ainos_xpc.c"
                "../ainos_xpc.c"
                "../../platform/darwin/ainos_xpc.c"
            )
            for f in "${search_files[@]}"; do
                if [[ -f "$f" ]]; then
                    xpc_source_file="$f"
                    break
                fi
            done

            if [[ -n "$xpc_source_file" ]]; then
                log_info "Building XPC service from $xpc_source_file..."
                local build_dir=$(mktemp -d)
                local xpc_bundle="${build_dir}/${XPC_SERVICE_NAME}.xpc"

                mkdir -p "${xpc_bundle}/Contents/MacOS"
                mkdir -p "${xpc_bundle}/Contents/Resources"

                # Compile the XPC service
                clang -x objective-c -fobjc-arc \
                    -framework Foundation \
                    -framework Security \
                    -o "${xpc_bundle}/Contents/MacOS/${XPC_SERVICE_NAME}" \
                    "$xpc_source_file"

                # Create Info.plist for the XPC bundle
                cat > "${xpc_bundle}/Contents/Info.plist" << XPC_PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>${XPC_SERVICE_NAME}</string>
    <key>CFBundleName</key>
    <string>Ainos XPC Service</string>
    <key>CFBundlePackageType</key>
    <string>XPC!</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>XPCService</key>
    <dict>
        <key>ServiceType</key>
        <string>Application</string>
    </dict>
</dict>
</plist>
XPC_PLIST_EOF

                xpc_source="${xpc_bundle}"
            else
                log_warn "XPC source file not found, skipping XPC service installation."
                return 0
            fi
        else
            log_warn "clang not found, skipping XPC service installation."
            return 0
        fi
    fi

    # Install the XPC service bundle
    if [[ -n "$xpc_source" ]]; then
        rm -rf "$XPC_SERVICE_BUNDLE"
        cp -R "$xpc_source" "$XPC_SERVICE_BUNDLE"
        chown -R root:wheel "$XPC_SERVICE_BUNDLE"
        chmod -R 755 "$XPC_SERVICE_BUNDLE"
        log_info "XPC service installed: $XPC_SERVICE_BUNDLE"
    fi
}

# ============================================================================
# Launchd Plist Installation
# ============================================================================

install_launchd_plist() {
    log_step "Installing launchd plist..."

    local plist_source=""

    # Look for the plist file
    local search_paths=(
        "./com.ainos.daemon.plist"
        "../com.ainos.daemon.plist"
        "../../platform/darwin/com.ainos.daemon.plist"
    )

    for path in "${search_paths[@]}"; do
        if [[ -f "$path" ]]; then
            plist_source="$path"
            break
        fi
    done

    if [[ -z "$plist_source" ]]; then
        log_warn "launchd plist not found. Creating default plist..."

        # Use the bundled plist from the current directory
        plist_source="./com.ainos.daemon.plist"
        if [[ ! -f "$plist_source" ]]; then
            # Create a minimal plist
            cat > "$plist_source" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ainos.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/lib/ainos/bin/ai-daemon</string>
        <string>--config</string>
        <string>/usr/local/etc/ainos/ai-daemon.conf</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/ainos/daemon-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/ainos/daemon-stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>AINOS_HOME</key>
        <string>/usr/local/lib/ainos</string>
        <key>RUST_LOG</key>
        <string>info,ainos=debug</string>
    </dict>
    <key>MachServices</key>
    <dict>
        <key>com.ainos.daemon.xpc</key>
        <true/>
    </dict>
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
</dict>
</plist>
PLIST_EOF
            log_info "Created default plist"
        fi
    fi

    # Copy the plist
    cp "$plist_source" "$LAUNCHD_PLIST"
    chmod 644 "$LAUNCHD_PLIST"
    chown root:wheel "$LAUNCHD_PLIST"

    log_info "launchd plist installed: $LAUNCHD_PLIST"
}

# ============================================================================
# Config File Installation
# ============================================================================

install_config() {
    log_step "Installing Ainos configuration..."

    local config_source=""

    # Look for config files
    local search_paths=(
        "./ai-daemon.conf"
        "./ai-daemon.toml"
        "../ai-daemon.conf"
        "../../configs/ai-daemon.conf"
        "../../configs/ai-daemon.toml"
    )

    for path in "${search_paths[@]}"; do
        if [[ -f "$path" ]]; then
            config_source="$path"
            break
        fi
    done

    if [[ -z "$config_source" ]]; then
        log_warn "Config file not found. Creating default config..."

        cat > "${AINOS_CONFIG_DIR}/ai-daemon.conf" << 'CONFIG_EOF'
# Ainos AI Daemon Configuration - macOS
models_dir = "/usr/local/lib/ainos/models"
default_model = "phi-3-mini-4k-instruct-q4.gguf"
socket_path = "127.0.0.1:9500"
enable_local = true
local_engine = "ggml"
max_concurrent_inferences = 2
model_cache_size_mb = 4096
inference_timeout_secs = 120
enable_cloud = true
cloud_api_url = "https://api.weelinking.com/v1"
cloud_api_key = ""
cloud_model = "gpt-5.6-sol"
network_check_interval = 30
cloud_fallback_confidence = 0.6
context_dir = "/var/db/ainos/contexts"
max_contexts = 1000
context_ttl_days = 30
log_level = "info"
audit_log = "/var/log/ainos/audit.log"
CONFIG_EOF
        log_info "Created default config"
        config_source="${AINOS_CONFIG_DIR}/ai-daemon.conf"
    else
        cp "$config_source" "${AINOS_CONFIG_DIR}/ai-daemon.conf"
    fi

    chmod 644 "${AINOS_CONFIG_DIR}/ai-daemon.conf"
    chown root:wheel "${AINOS_CONFIG_DIR}/ai-daemon.conf"

    log_info "Configuration installed: ${AINOS_CONFIG_DIR}/ai-daemon.conf"
}

# ============================================================================
# Log Rotation Setup (newsyslog)
# ============================================================================

setup_log_rotation() {
    log_step "Setting up log rotation (newsyslog)..."

    mkdir -p /etc/newsyslog.d

    cat > "$NEWSYSLOG_CONF" << NEWSYSLOG_EOF
# Ainos OS log rotation configuration
# Managed by: Ainos macOS installer
# Format: <file> <owner:group> <mode> <count> <size> <when> <flags>

/var/log/ainos/daemon-stdout.log    root:wheel   644   7    10240    *    Z
/var/log/ainos/daemon-stderr.log    root:wheel   644   7    10240    *    Z
/var/log/ainos/audit.log           root:wheel   640   30   51200    *    ZJ
/var/log/ainos/thermal.log         root:wheel   644   14   10240    *    Z
NEWSYSLOG_EOF

    chmod 644 "$NEWSYSLOG_CONF"
    chown root:wheel "$NEWSYSLOG_CONF"

    log_info "Log rotation configured: $NEWSYSLOG_CONF"
}

# ============================================================================
# Firewall Configuration
# ============================================================================

configure_firewall() {
    log_step "Configuring macOS firewall..."

    if ! command -v /usr/libexec/ApplicationFirewall/socketfilterfw &> /dev/null; then
        log_warn "socketfilterfw not found. Skipping firewall configuration."
        return 0
    fi

    # Check if firewall is enabled
    local firewall_status=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>&1)

    if echo "$firewall_status" | grep -q "State = 1"; then
        log_info "Firewall is enabled. Adding Ainos daemon rule..."

        # Add the daemon binary to the firewall whitelist
        if [[ -f "${AINOS_BIN_DIR}/ai-daemon" ]]; then
            /usr/libexec/ApplicationFirewall/socketfilterfw \
                --add "${AINOS_BIN_DIR}/ai-daemon" 2>/dev/null || true
            log_info "Added daemon to firewall whitelist"
        fi

        # Add the XPC service to the firewall whitelist
        if [[ -d "$XPC_SERVICE_BUNDLE" ]]; then
            /usr/libexec/ApplicationFirewall/socketfilterfw \
                --add "${XPC_SERVICE_BUNDLE}/Contents/MacOS/${XPC_SERVICE_NAME}" 2>/dev/null || true
            log_info "Added XPC service to firewall whitelist"
        fi
    else
        log_info "Firewall is disabled. No configuration needed."
    fi
}

# ============================================================================
# Launchd Service Loading
# ============================================================================

load_launchd_service() {
    log_step "Loading launchd service..."

    # Unload if already loaded
    if launchctl list | grep -q "com.ainos.daemon"; then
        log_info "Unloading existing service..."
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    fi

    # Load the service
    launchctl load "$LAUNCHD_PLIST"
    log_info "launchd service loaded"

    # Start the service
    launchctl start com.ainos.daemon
    log_info "launchd service started"

    # Verify the service is running
    sleep 1
    if launchctl list | grep -q "com.ainos.daemon"; then
        local pid=$(launchctl list | grep "com.ainos.daemon" | awk '{print $1}')
        if [[ "$pid" != "-" && -n "$pid" ]]; then
            log_info "Ainos daemon is running (PID: $pid)"
        else
            log_warn "Ainos daemon service loaded but not running (check logs)"
        fi
    else
        log_warn "Ainos daemon service not found in launchctl list"
    fi
}

# ============================================================================
# Code Signing Verification
# ============================================================================

verify_codesigning() {
    log_step "Verifying code signing..."

    local binaries=(
        "${AINOS_BIN_DIR}/ai-daemon"
    )

    if [[ -d "$XPC_SERVICE_BUNDLE" ]]; then
        binaries+=("${XPC_SERVICE_BUNDLE}/Contents/MacOS/${XPC_SERVICE_NAME}")
    fi

    for binary in "${binaries[@]}"; do
        if [[ -f "$binary" ]]; then
            if codesign -dv "$binary" 2>&1 | grep -q "adhoc"; then
                log_warn "$(basename "$binary") is signed with ad-hoc signature"
            elif codesign -dv "$binary" 2>/dev/null; then
                log_info "$(basename "$binary"): Code signature verified"
            else
                log_warn "$(basename "$binary"): Not code signed"
            fi
        fi
    done
}

# ============================================================================
# Status Check
# ============================================================================

check_status() {
    echo ""
    log_info "=== AinosOS Installation Status ==="
    echo ""

    # Check directories
    local required_dirs=(
        "$AINOS_PREFIX"
        "$AINOS_BIN_DIR"
        "$AINOS_LIB_DIR"
        "$AINOS_MODELS_DIR"
        "$AINOS_CONFIG_DIR"
        "$AINOS_LOG_DIR"
        "$AINOS_RUN_DIR"
    )

    echo "Directories:"
    for dir in "${required_dirs[@]}"; do
        if [[ -d "$dir" ]]; then
            echo -e "  ${GREEN}✓${NC} $dir"
        else
            echo -e "  ${RED}✗${NC} $dir"
        fi
    done

    # Check daemon binary
    echo ""
    echo "Daemon Binary:"
    if [[ -f "${AINOS_BIN_DIR}/ai-daemon" ]]; then
        local size=$(stat -f%z "${AINOS_BIN_DIR}/ai-daemon" 2>/dev/null || stat -c%s "${AINOS_BIN_DIR}/ai-daemon" 2>/dev/null || echo "unknown")
        echo -e "  ${GREEN}✓${NC} ai-daemon ($(numfmt --to=iec $size 2>/dev/null || echo "${size} bytes"))"
    else
        echo -e "  ${RED}✗${NC} ai-daemon (not found)"
    fi

    # Check launchd plist
    echo ""
    echo "launchd Service:"
    if [[ -f "$LAUNCHD_PLIST" ]]; then
        echo -e "  ${GREEN}✓${NC} $LAUNCHD_PLIST"
    else
        echo -e "  ${RED}✗${NC} $LAUNCHD_PLIST"
    fi

    if launchctl list | grep -q "com.ainos.daemon"; then
        local pid=$(launchctl list | grep "com.ainos.daemon" | awk '{print $1}')
        echo -e "  ${GREEN}✓${NC} Service loaded (PID: $pid)"
    else
        echo -e "  ${RED}✗${NC} Service not loaded"
    fi

    # Check XPC service
    echo ""
    echo "XPC Service:"
    if [[ -d "$XPC_SERVICE_BUNDLE" ]]; then
        echo -e "  ${GREEN}✓${NC} $XPC_SERVICE_BUNDLE"
    else
        echo -e "  ${YELLOW}⚠${NC} XPC service not installed"
    fi

    # Check log rotation
    echo ""
    echo "Log Rotation:"
    if [[ -f "$NEWSYSLOG_CONF" ]]; then
        echo -e "  ${GREEN}✓${NC} $NEWSYSLOG_CONF"
    else
        echo -e "  ${YELLOW}⚠${NC} Log rotation not configured"
    fi

    # Check config
    echo ""
    echo "Configuration:"
    if [[ -f "${AINOS_CONFIG_DIR}/ai-daemon.conf" ]]; then
        echo -e "  ${GREEN}✓${NC} ${AINOS_CONFIG_DIR}/ai-daemon.conf"
    else
        echo -e "  ${YELLOW}⚠${NC} Config not found"
    fi

    # Check thermal policy
    echo ""
    echo "Thermal Monitoring:"
    if [[ -f "$AINOS_RUN_DIR/thermal_policy" ]]; then
        echo -e "  ${GREEN}✓${NC} Thermal policy file exists"
    else
        echo -e "  ${YELLOW}⚠${NC} Thermal policy not yet written (daemon may not be running)"
    fi

    echo ""
    log_info "Status check complete"
}

# ============================================================================
# Uninstall
# ============================================================================

uninstall() {
    log_step "Uninstalling AinosOS..."

    # Stop and unload the launchd service
    if launchctl list | grep -q "com.ainos.daemon"; then
        log_info "Stopping and unloading launchd service..."
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    fi

    # Remove launchd plist
    if [[ -f "$LAUNCHD_PLIST" ]]; then
        rm -f "$LAUNCHD_PLIST"
        log_info "Removed: $LAUNCHD_PLIST"
    fi

    # Remove newsyslog config
    if [[ -f "$NEWSYSLOG_CONF" ]]; then
        rm -f "$NEWSYSLOG_CONF"
        log_info "Removed: $NEWSYSLOG_CONF"
    fi

    # Remove Ainos directories
    if [[ -d "$AINOS_PREFIX" ]]; then
        log_info "Removing Ainos files from $AINOS_PREFIX..."
        rm -rf "$AINOS_PREFIX" 2>/dev/null || {
            log_warn "Could not remove $AINOS_PREFIX (files may be in use)"
        }
    fi

    # Ask about removing log files
    if [[ -d "$AINOS_LOG_DIR" ]]; then
        echo ""
        read -p "Remove log files in $AINOS_LOG_DIR? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$AINOS_LOG_DIR"
            log_info "Log files removed"
        else
            log_info "Log files preserved"
        fi
    fi

    # Ask about removing config
    if [[ -d "$AINOS_CONFIG_DIR" ]]; then
        echo ""
        read -p "Remove configuration files in $AINOS_CONFIG_DIR? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$AINOS_CONFIG_DIR"
            log_info "Configuration removed"
        else
            log_info "Configuration preserved"
        fi
    fi

    # Remove firewall rules
    if command -v /usr/libexec/ApplicationFirewall/socketfilterfw &> /dev/null; then
        log_info "Removing firewall rules..."
        if [[ -f "${AINOS_BIN_DIR}/ai-daemon" ]]; then
            /usr/libexec/ApplicationFirewall/socketfilterfw \
                --remove "${AINOS_BIN_DIR}/ai-daemon" 2>/dev/null || true
        fi
    fi

    log_info "Uninstall complete"
}

# ============================================================================
# Main Installation
# ============================================================================

show_help() {
    echo "AinosOS macOS Installer v${VERSION}"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  --help        Show this help message"
    echo "  --status      Check installation status"
    echo "  --upgrade     Upgrade existing installation (reloads config)"
    echo "  --uninstall   Remove all Ainos components"
    echo ""
    echo "Without options, performs a full installation."
}

install() {
    echo ""
    echo "============================================"
    echo "  AinosOS macOS Installer v${VERSION}"
    echo "============================================"
    echo ""

    check_root
    check_macos

    echo ""
    log_info "Starting installation..."

    # Run installation steps
    setup_directories
    install_daemon_binary
    install_xpc_service
    install_launchd_plist
    install_config
    setup_log_rotation
    configure_firewall
    load_launchd_service
    verify_codesigning

    echo ""
    echo "============================================"
    echo -e "${GREEN}  AinosOS Installation Complete!${NC}"
    echo "============================================"
    echo ""
    echo "  Daemon:     ${AINOS_BIN_DIR}/ai-daemon"
    echo "  Config:     ${AINOS_CONFIG_DIR}/ai-daemon.conf"
    echo "  Logs:       ${AINOS_LOG_DIR}"
    echo "  XPC:        ${XPC_SERVICE_BUNDLE}"
    echo ""
    echo "  Manage:"
    echo "    sudo launchctl start com.ainos.daemon"
    echo "    sudo launchctl stop com.ainos.daemon"
    echo "    sudo launchctl list | grep ainos"
    echo ""
    echo "  View logs:"
    echo "    log stream --predicate 'subsystem == \"com.ainos.daemon\"'"
    echo "    log show --predicate 'subsystem == \"com.ainos.daemon\"' --last 1h"
    echo ""
    echo "============================================"
}

upgrade() {
    log_step "Upgrading AinosOS installation..."

    check_root
    check_macos

    # Upgrade the daemon binary
    install_daemon_binary

    # Upgrade the XPC service
    install_xpc_service

    # Reload the launchd service
    if launchctl list | grep -q "com.ainos.daemon"; then
        log_info "Reloading launchd service..."
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
        launchctl load "$LAUNCHD_PLIST"
        launchctl start com.ainos.daemon
        log_info "Service reloaded"
    else
        log_info "Service not loaded, loading now..."
        load_launchd_service
    fi

    log_info "Upgrade complete"
}

# ============================================================================
# Entry Point
# ============================================================================

case "${1:-}" in
    --help|-h)
        show_help
        ;;
    --status|-s)
        check_root
        check_status
        ;;
    --uninstall|-u)
        check_root
        uninstall
        ;;
    --upgrade|-U)
        upgrade
        ;;
    "")
        install
        ;;
    *)
        log_error "Unknown option: $1"
        echo "Usage: $0 [--help|--status|--upgrade|--uninstall]"
        exit 1
        ;;
esac