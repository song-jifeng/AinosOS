#!/bin/bash
# Ainos OS - Log Rotation Script
# 按大小轮转日志 (超过 100MB 自动归档)，保留最近 7 天
# 用法: ./rotate_logs.sh [日志目录] [最大大小MB] [保留天数] [日志模式]
# 示例: ./rotate_logs.sh /var/log/ainos 100 7 "*.log"

set -euo pipefail

# ============ 配置 ============
LOG_DIR="${1:-/var/log/ainos}"
MAX_SIZE_MB="${2:-100}"
RETENTION_DAYS="${3:-7}"
LOG_PATTERN="${4:-*.log}"

# 时间戳
TIMESTAMP=$(date "+%Y%m%d_%H%M%S")
SCRIPT_NAME="rotate_logs"

# ============ 颜色输出 ============
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[${SCRIPT_NAME}]${NC} $1"; }
warn()  { echo -e "${YELLOW}[${SCRIPT_NAME}] WARN: $1${NC}" >&2; }
error() { echo -e "${RED}[${SCRIPT_NAME}] ERROR: $1${NC}" >&2; }

# ============ 参数校验 ============
if [ ! -d "$LOG_DIR" ]; then
    error "Directory '$LOG_DIR' does not exist"
    exit 1
fi

if ! [[ "$MAX_SIZE_MB" =~ ^[0-9]+$ ]] || [ "$MAX_SIZE_MB" -le 0 ]; then
    error "MAX_SIZE_MB must be a positive integer, got '$MAX_SIZE_MB'"
    exit 1
fi

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [ "$RETENTION_DAYS" -le 0 ]; then
    error "RETENTION_DAYS must be a positive integer, got '$RETENTION_DAYS'"
    exit 1
fi

info "Starting log rotation: dir=$LOG_DIR, max_size=${MAX_SIZE_MB}MB, retention=${RETENTION_DAYS}d, pattern=$LOG_PATTERN"

# ============ 统计变量 ============
ROTATED_COUNT=0
CLEANED_COUNT=0
TOTAL_SIZE_BEFORE=0
TOTAL_SIZE_AFTER=0

# ============ 1. 轮转超过大小限制的日志文件 ============
info "Rotating log files exceeding ${MAX_SIZE_MB}MB..."

while IFS= read -r -d '' logfile; do
    # 获取文件大小 (bytes)
    file_size=$(stat -c%s "$logfile" 2>/dev/null || stat -f%z "$logfile" 2>/dev/null)
    TOTAL_SIZE_BEFORE=$((TOTAL_SIZE_BEFORE + file_size))

    # 获取文件修改时间用于归档名
    file_mtime=$(date -r "$logfile" "+%Y%m%d_%H%M%S" 2>/dev/null || echo "$TIMESTAMP")

    basename=$(basename "$logfile")
    dirname=$(dirname "$logfile")
    archive_name="${basename}.${file_mtime}.gz"
    archive_path="${dirname}/${archive_name}"

    # 检查归档文件是否已存在
    if [ -f "$archive_path" ]; then
        archive_name="${basename}.${file_mtime}.${RANDOM}.gz"
        archive_path="${dirname}/${archive_name}"
    fi

    info "Rotating: $logfile (${file_size} bytes) -> $archive_path"

    # 压缩并清空原日志文件 (不中断写入进程)
    if gzip -c "$logfile" > "$archive_path"; then
        : > "$logfile"  # 清空原文件，保持文件句柄有效
        compressed_size=$(stat -c%s "$archive_path" 2>/dev/null || stat -f%z "$archive_path" 2>/dev/null || echo 0)
        TOTAL_SIZE_AFTER=$((TOTAL_SIZE_AFTER + compressed_size))
        ROTATED_COUNT=$((ROTATED_COUNT + 1))
        info "  Compressed: $archive_name (${compressed_size} bytes, saved $((file_size - compressed_size)) bytes)"
    else
        warn "  Failed to compress: $logfile"
        rm -f "$archive_path"
    fi
done < <(find "$LOG_DIR" -type f -name "$LOG_PATTERN" -size "+${MAX_SIZE_MB}M" -print0 2>/dev/null)

# ============ 2. 清理超过保留天数的归档文件 ============
if [ "$RETENTION_DAYS" -gt 0 ]; then
    info "Removing archived logs older than ${RETENTION_DAYS} days..."

    while IFS= read -r -d '' old_archive; do
        old_size=$(stat -c%s "$old_archive" 2>/dev/null || stat -f%z "$old_archive" 2>/dev/null || echo 0)
        info "  Removing: $old_archive (${old_size} bytes)"
        rm -f "$old_archive"
        CLEANED_COUNT=$((CLEANED_COUNT + 1))
    done < <(find "$LOG_DIR" -type f -name "*.gz" -mtime "+${RETENTION_DAYS}" -print0 2>/dev/null)
fi

# ============ 3. 报告 ============
info "Rotation complete: rotated=$ROTATED_COUNT, cleaned=$CLEANED_COUNT, total_saved=$((TOTAL_SIZE_BEFORE - TOTAL_SIZE_AFTER)) bytes"

# ============ 4. 配置 logrotate (如果可用) ============
if command -v logrotate &>/dev/null; then
    # 生成 logrotate 配置
    LOGROTATE_CONF="/etc/logrotate.d/ainos-ai-daemon"
    if [ ! -f "$LOGROTATE_CONF" ]; then
        info "logrotate detected. To enable automatic rotation, create: $LOGROTATE_CONF"
        cat << 'EOF'
# 示例 logrotate 配置 (aicmd 或手动创建 /etc/logrotate.d/ainos-ai-daemon):
# /var/log/ainos/*.log {
#     daily
#     rotate 7
#     size 100M
#     compress
#     delaycompress
#     missingok
#     notifempty
#     copytruncate
#     postrotate
#         # 重启 daemon 或发送 SIGHUP
#         # systemctl reload ainos-ai-daemon || true
#     endscript
# }
EOF
    fi
fi

exit 0