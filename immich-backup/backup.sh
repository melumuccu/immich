#!/usr/bin/env bash
set -Eeuo pipefail

export TZ="${TZ:-Asia/Tokyo}"
export PATH="${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

RCLONE_BIN="${RCLONE_BIN:-/usr/bin/rclone}"

BACKUP_NAME="${BACKUP_NAME:-Immich backup}"
BACKUP_TARGETS="${BACKUP_TARGETS:-}"
BACKUP_TEST_SOURCE="${BACKUP_TEST_SOURCE:-}"
BACKUP_TEST_DEST="${BACKUP_TEST_DEST:-}"
BACKUP_PROD_SOURCE="${BACKUP_PROD_SOURCE:-}"
BACKUP_PROD_DEST="${BACKUP_PROD_DEST:-}"
BACKUP_BACKUPS_SOURCE="${BACKUP_BACKUPS_SOURCE:-}"
BACKUP_BACKUPS_DEST="${BACKUP_BACKUPS_DEST:-}"
BACKUP_UPLOAD_SOURCE="${BACKUP_UPLOAD_SOURCE:-}"
BACKUP_UPLOAD_DEST="${BACKUP_UPLOAD_DEST:-}"
BACKUP_PROFILE_SOURCE="${BACKUP_PROFILE_SOURCE:-}"
BACKUP_PROFILE_DEST="${BACKUP_PROFILE_DEST:-}"

RCLONE_FLAGS=(
  --verbose
  --delete-after
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

target_key() {
  local target="$1"

  printf '%s' "${target}" | tr '[:lower:]-' '[:upper:]_'
}

validate_target_name() {
  local target="$1"

  case "${target}" in
    "" | *[!A-Za-z0-9_-]*)
      log "ERROR: invalid backup target name: ${target}"
      return 1
      ;;
  esac
}

validate_target_env() {
  local target="$1"
  local key

  validate_target_name "${target}" || return 1
  key="$(target_key "${target}")"
  validate_required_env "${target} backup" "BACKUP_${key}_SOURCE" "BACKUP_${key}_DEST"
}

validate_backup_env() {
  local missing=0
  local target

  if [[ -z "${BACKUP_TARGETS//[[:space:],]/}" ]]; then
    log "ERROR: BACKUP_TARGETS must include at least one target"
    return 1
  fi

  IFS=',' read -ra targets <<< "${BACKUP_TARGETS}"
  for target in "${targets[@]}"; do
    validate_target_env "${target}" || missing=1
  done

  return "${missing}"
}

sync_target_path() {
  local target="$1"
  local key source_var dest_var

  key="$(target_key "${target}")"
  source_var="BACKUP_${key}_SOURCE"
  dest_var="BACKUP_${key}_DEST"

  sync_path "${!source_var}" "${!dest_var}"
}

sync_targets() {
  local target

  IFS=',' read -ra targets <<< "${BACKUP_TARGETS}"
  for target in "${targets[@]}"; do
    sync_target_path "${target}"
  done
}

log "${BACKUP_NAME} backup started"
log "Using rclone remote from environment: b2"
validate_rclone_env
validate_backup_env

sync_targets
