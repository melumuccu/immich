#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Asia/Tokyo}"
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

BACKUP_CRON="${BACKUP_CRON:-30 2 * * *}"
if [[ -z "${BACKUP_CRON//[[:space:]]/}" ]]; then
  BACKUP_CRON="30 2 * * *"
fi

umask 077
export -p > /etc/container.env

printf '%s\n' \
  'SHELL=/bin/bash' \
  "PATH=${PATH}" \
  "TZ=${TZ}" \
  "${BACKUP_CRON} source /etc/container.env && /app/backup.sh >> /proc/1/fd/1 2>> /proc/1/fd/2" \
  > /etc/crontabs/root

printf '[%s] %s backup scheduled: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${BACKUP_NAME:-Immich backup}" "${BACKUP_CRON}"

exec crond -f -l 8 -L /proc/1/fd/1
