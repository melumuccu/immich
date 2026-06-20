#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Asia/Tokyo}"
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

RCLONE_BIN="${RCLONE_BIN:-/usr/bin/rclone}"

BACKUP_NAME="${BACKUP_NAME:-Immich backup}"
BACKUP_MODE="${BACKUP_MODE:-}"
BACKUP_TEST_SOURCE="${BACKUP_TEST_SOURCE:-}"
BACKUP_TEST_DEST="${BACKUP_TEST_DEST:-}"
BACKUP_PROD_SOURCE="${BACKUP_PROD_SOURCE:-}"
BACKUP_PROD_DEST="${BACKUP_PROD_DEST:-}"
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
  case "$1" in
    1 | [Tt][Rr][Uu][Ee] | [Yy][Ee][Ss] | [Oo][Nn]) return 0 ;;
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

validate_required_env() {
  local label="$1"
  local missing=0
  shift

  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      log "ERROR: required ${label} environment variable is not set: ${name}"
      missing=1
    fi
  done

  return "${missing}"
}

validate_mode_env() {
  case "${BACKUP_MODE}" in
    "")
      return 0
      ;;
    test)
      validate_required_env "test backup" BACKUP_TEST_SOURCE BACKUP_TEST_DEST
      ;;
    prod)
      validate_required_env "prod backup" BACKUP_PROD_SOURCE BACKUP_PROD_DEST
      ;;
    *)
      log "ERROR: BACKUP_MODE must be either 'test' or 'prod': ${BACKUP_MODE}"
      return 1
      ;;
  esac
}

validate_backup_env() {
  local missing=0

  validate_mode_env || missing=1

  if is_truthy "${BACKUP_SETTINGS_ENABLED}"; then
    validate_required_env "settings backup" BACKUP_SETTINGS_SOURCE BACKUP_SETTINGS_DEST || missing=1
  fi

  return "${missing}"
}

sync_mode_path() {
  case "${BACKUP_MODE}" in
    "")
      log "Skip data sync"
      ;;
    test)
      sync_path "${BACKUP_TEST_SOURCE}" "${BACKUP_TEST_DEST}"
      ;;
    prod)
      sync_path "${BACKUP_PROD_SOURCE}" "${BACKUP_PROD_DEST}"
      ;;
  esac
}

sync_settings_path() {
  if ! is_truthy "${BACKUP_SETTINGS_ENABLED}"; then
    log "Skip settings sync"
    return 0
  fi

  sync_path "${BACKUP_SETTINGS_SOURCE}" "${BACKUP_SETTINGS_DEST}"
}

log "${BACKUP_NAME} backup started"
log "Using rclone remote from environment: b2"
validate_rclone_env
validate_backup_env

sync_mode_path
sync_settings_path
