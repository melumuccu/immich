#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Asia/Tokyo}"
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

RCLONE_BIN="${RCLONE_BIN:-/usr/bin/rclone}"

# TEST
KOKI_TEST_SOURCE="/data/library/admin/2026"
KOKI_TEST_DEST="b2:immich-koki/admin/2026"

# PRODUCTION
KOKI_PRODUCTION_SOURCE="/data/library/admin"
KOKI_PRODUCTION_DEST="b2:immich-koki"

SETTINGS_SOURCE="/data/settings"
SETTINGS_DEST="b2:immich-settings"

RCLONE_FLAGS=(
  --verbose
)

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

sync_path() {
  local source_path="$1"
  local dest_path="$2"

  if [[ ! -d "${source_path}" ]]; then
    log "ERROR: source directory does not exist: ${source_path}"
    return 1
  fi

  log "Sync start: ${source_path} -> ${dest_path}"
  "${RCLONE_BIN}" sync "${source_path}" "${dest_path}" "${RCLONE_FLAGS[@]}"
  log "Sync done: ${source_path} -> ${dest_path}"
}

finish() {
  local status=$?

  if [[ ${status} -eq 0 ]]; then
    log "Immich backup finished successfully"
  else
    log "Immich backup failed with exit code ${status}"
  fi
}
trap finish EXIT

validate_rclone_env() {
  local missing=0

  for name in RCLONE_CONFIG_B2_TYPE RCLONE_CONFIG_B2_ACCOUNT RCLONE_CONFIG_B2_KEY; do
    if [[ -z "${!name:-}" ]]; then
      log "ERROR: required rclone environment variable is not set: ${name}"
      missing=1
    fi
  done

  return "${missing}"
}

log "Immich backup started"
log "Using rclone remote from environment: b2"
validate_rclone_env

# TEST
# sync_path "${KOKI_TEST_SOURCE}" "${KOKI_TEST_DEST}"

# PRODUCTION
sync_path "${KOKI_PRODUCTION_SOURCE}" "${KOKI_PRODUCTION_DEST}"
sync_path "${SETTINGS_SOURCE}" "${SETTINGS_DEST}"
