#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Asia/Tokyo}"
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

RCLONE_BIN="${RCLONE_BIN:-/usr/bin/rclone}"

BACKUP_NAME="${BACKUP_NAME:-Immich backup}"
BACKUP_TEST_ENABLED="${BACKUP_TEST_ENABLED:-false}"
BACKUP_TEST_SOURCE="${BACKUP_TEST_SOURCE:-}"
BACKUP_TEST_DEST="${BACKUP_TEST_DEST:-}"
BACKUP_PRODUCTION_ENABLED="${BACKUP_PRODUCTION_ENABLED:-true}"
BACKUP_PRODUCTION_SOURCE="${BACKUP_PRODUCTION_SOURCE:-}"
BACKUP_PRODUCTION_DEST="${BACKUP_PRODUCTION_DEST:-}"
BACKUP_SETTINGS_ENABLED="${BACKUP_SETTINGS_ENABLED:-false}"
BACKUP_SETTINGS_SOURCE="${BACKUP_SETTINGS_SOURCE:-}"
BACKUP_SETTINGS_DEST="${BACKUP_SETTINGS_DEST:-}"

RCLONE_FLAGS=(
  --verbose
)

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

is_truthy() {
  case "${1,,}" in
    1 | true | yes | on) return 0 ;;
    *) return 1 ;;
  esac
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
    log "${BACKUP_NAME} backup finished successfully"
  else
    log "${BACKUP_NAME} backup failed with exit code ${status}"
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

validate_sync_env() {
  local label="$1"
  local enabled_var="$2"
  local source_var="$3"
  local dest_var="$4"
  local missing=0

  if ! is_truthy "${!enabled_var:-false}"; then
    return 0
  fi

  for name in "${source_var}" "${dest_var}"; do
    if [[ -z "${!name:-}" ]]; then
      log "ERROR: required ${label} environment variable is not set: ${name}"
      missing=1
    fi
  done

  return "${missing}"
}

validate_backup_env() {
  local missing=0

  validate_sync_env "test backup" BACKUP_TEST_ENABLED BACKUP_TEST_SOURCE BACKUP_TEST_DEST || missing=1
  validate_sync_env "production backup" BACKUP_PRODUCTION_ENABLED BACKUP_PRODUCTION_SOURCE BACKUP_PRODUCTION_DEST || missing=1
  validate_sync_env "settings backup" BACKUP_SETTINGS_ENABLED BACKUP_SETTINGS_SOURCE BACKUP_SETTINGS_DEST || missing=1

  return "${missing}"
}

sync_enabled_path() {
  local label="$1"
  local enabled="$2"
  local source_path="$3"
  local dest_path="$4"

  if ! is_truthy "${enabled}"; then
    log "Skip ${label} sync"
    return 0
  fi

  sync_path "${source_path}" "${dest_path}"
}

log "${BACKUP_NAME} backup started"
log "Using rclone remote from environment: b2"
validate_rclone_env
validate_backup_env

# TEST
sync_enabled_path "test" "${BACKUP_TEST_ENABLED}" "${BACKUP_TEST_SOURCE}" "${BACKUP_TEST_DEST}"

# PRODUCTION
sync_enabled_path "production" "${BACKUP_PRODUCTION_ENABLED}" "${BACKUP_PRODUCTION_SOURCE}" "${BACKUP_PRODUCTION_DEST}"

# SETTINGS
sync_enabled_path "settings" "${BACKUP_SETTINGS_ENABLED}" "${BACKUP_SETTINGS_SOURCE}" "${BACKUP_SETTINGS_DEST}"
