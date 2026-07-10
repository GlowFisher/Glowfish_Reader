#!/usr/bin/env bash
# 每日备份授权账本（席位真相源，丢了无法重建）。
# 装 cron：  5 3 * * *  /opt/glowfish/account-server/deploy/backup_db.sh
set -euo pipefail

DB="${LICENSE_DB:-/var/lib/glowfish/account.db}"
DEST="${BACKUP_DIR:-/var/backups/glowfish}"
KEEP="${KEEP:-30}"          # 本地保留份数

mkdir -p "$DEST"
STAMP="$(date +%F_%H%M)"
OUT="$DEST/license-$STAMP.db"

# .backup 是热备份，运行中也能安全快照
sqlite3 "$DB" ".backup '$OUT'"
echo "backed up -> $OUT"

# 清理超出保留份数的旧备份
ls -1t "$DEST"/license-*.db 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

# 异地留存（可选，账本极小强烈建议开）。用通用的 rclone：先 `rclone config` 配好任意
# remote（阿里云 OSS / 腾讯云 COS / S3 / WebDAV 皆可），再设环境变量即自动推送：
#   OFFSITE_RCLONE_REMOTE="oss:glowfish-backup/shupai"   # 形如 <remote>:<bucket>/<前缀>
# cron 行可写：  5 3 * * *  OFFSITE_RCLONE_REMOTE="oss:..."  /opt/shupai/.../backup_db.sh
if [ -n "${OFFSITE_RCLONE_REMOTE:-}" ]; then
  if command -v rclone >/dev/null 2>&1; then
    if rclone copy "$OUT" "$OFFSITE_RCLONE_REMOTE/"; then
      echo "offsite -> $OFFSITE_RCLONE_REMOTE"
    else
      echo "⚠ 异地备份失败（本地备份已完成，不阻断）" >&2
    fi
  else
    echo "⚠ 设了 OFFSITE_RCLONE_REMOTE 但未装 rclone，跳过异地备份" >&2
  fi
fi
