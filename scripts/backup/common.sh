#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Backup Common Library
# NE PAS EXECUTER DIRECTEMENT — source par les scripts de backup
# =============================================================================

# Guard against direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced, not executed directly."
    echo "Usage: source $(basename "${BASH_SOURCE[0]}")"
    exit 1
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEPLOY_DIR="/opt/cri-platform"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="${DEPLOY_DIR}/.env"
BACKUP_BASE="/var/backups/cri"
LOG_DIR="/var/log/cri-backup"
GPG_PASSPHRASE_FILE="${BACKUP_GPG_PASSPHRASE_FILE:-/opt/cri-platform/.backup-gpg-passphrase}"
BACKUP_BUCKET="${BACKUP_MINIO_BUCKET:-cri-backups}"
RETENTION_DAILY_DAYS="${BACKUP_RETENTION_DAILY_DAYS:-30}"
RETENTION_MONTHLY_MONTHS="${BACKUP_RETENTION_MONTHLY_MONTHS:-12}"

# Date helpers
TODAY=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
YEAR=$(date +%Y)
MONTH=$(date +%m)

# Script identity (set by each caller before sourcing)
SCRIPT_NAME="${SCRIPT_NAME:-backup}"
LOG_FILE="${LOG_DIR}/${SCRIPT_NAME}.log"
LOCK_FILE="/var/run/cri-backup-${SCRIPT_NAME}.lock"

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
load_env() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        log_error "Environment file not found: ${ENV_FILE}"
        return 1
    fi

    local perms
    perms=$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%Lp' "${ENV_FILE}" 2>/dev/null)
    if [[ "${perms}" != "600" ]]; then
        log_warn "Environment file permissions are ${perms}, expected 600"
    fi

    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a

    # Update configurable retention from env
    RETENTION_DAILY_DAYS="${BACKUP_RETENTION_DAILY_DAYS:-${RETENTION_DAILY_DAYS}}"
    RETENTION_MONTHLY_MONTHS="${BACKUP_RETENTION_MONTHLY_MONTHS:-${RETENTION_MONTHLY_MONTHS}}"
    BACKUP_BUCKET="${BACKUP_MINIO_BUCKET:-${BACKUP_BUCKET}}"
    GPG_PASSPHRASE_FILE="${BACKUP_GPG_PASSPHRASE_FILE:-${GPG_PASSPHRASE_FILE}}"
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log() {
    local level="$1"
    shift
    local msg="[${SCRIPT_NAME} $(date '+%Y-%m-%d %H:%M:%S')] [${level}] $*"
    echo "${msg}"
    echo "${msg}" >> "${LOG_FILE}" 2>/dev/null || true
}

log_info()  { _log "INFO"  "$@"; }
log_warn()  { _log "WARN"  "$@"; }
log_error() { _log "ERROR" "$@"; }

# ---------------------------------------------------------------------------
# Lock file management (prevent concurrent runs)
# ---------------------------------------------------------------------------
acquire_lock() {
    if [[ -f "${LOCK_FILE}" ]]; then
        local existing_pid
        existing_pid=$(cat "${LOCK_FILE}" 2>/dev/null)
        if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" 2>/dev/null; then
            log_error "Another instance is running (PID ${existing_pid}). Exiting."
            return 1
        fi
        log_warn "Removing stale lock file (PID ${existing_pid} is not running)"
        rm -f "${LOCK_FILE}"
    fi
    echo $$ > "${LOCK_FILE}"
    log_info "Lock acquired (PID $$)"
}

release_lock() {
    rm -f "${LOCK_FILE}" 2>/dev/null
}

# Register cleanup on exit
trap release_lock EXIT

# ---------------------------------------------------------------------------
# SHA-256 checksum helpers
# ---------------------------------------------------------------------------
compute_sha256() {
    local file="$1"
    sha256sum "${file}" | awk '{print $1}'
}

write_checksum() {
    local file="$1"
    local checksum
    checksum=$(compute_sha256 "${file}")
    echo "${checksum}  $(basename "${file}")" > "${file}.sha256"
    log_info "Checksum: ${checksum} → $(basename "${file}").sha256"
}

verify_sha256() {
    local file="$1"
    local checksum_file="${file}.sha256"
    if [[ ! -f "${checksum_file}" ]]; then
        log_error "Checksum file not found: ${checksum_file}"
        return 1
    fi
    local expected actual
    expected=$(awk '{print $1}' "${checksum_file}")
    actual=$(compute_sha256 "${file}")
    if [[ "${expected}" != "${actual}" ]]; then
        log_error "Checksum mismatch for $(basename "${file}"): expected=${expected}, actual=${actual}"
        return 1
    fi
    log_info "Checksum verified: $(basename "${file}")"
}

# ---------------------------------------------------------------------------
# GPG encryption / decryption
# ---------------------------------------------------------------------------
encrypt_file() {
    local file="$1"
    if [[ ! -f "${GPG_PASSPHRASE_FILE}" ]]; then
        log_error "GPG passphrase file not found: ${GPG_PASSPHRASE_FILE}"
        return 3
    fi
    gpg --symmetric --cipher-algo AES256 --batch --yes \
        --passphrase-file "${GPG_PASSPHRASE_FILE}" \
        --output "${file}.gpg" "${file}"
    if [[ $? -ne 0 ]]; then
        log_error "GPG encryption failed for $(basename "${file}")"
        return 3
    fi
    rm -f "${file}"
    log_info "Encrypted: $(basename "${file}") → $(basename "${file}").gpg"
}

decrypt_file() {
    local file="$1"
    local output="${file%.gpg}"
    if [[ ! -f "${GPG_PASSPHRASE_FILE}" ]]; then
        log_error "GPG passphrase file not found: ${GPG_PASSPHRASE_FILE}"
        return 3
    fi
    gpg --decrypt --batch --yes \
        --passphrase-file "${GPG_PASSPHRASE_FILE}" \
        --output "${output}" "${file}"
    if [[ $? -ne 0 ]]; then
        log_error "GPG decryption failed for $(basename "${file}")"
        return 3
    fi
    log_info "Decrypted: $(basename "${file}") → $(basename "${output}")"
}

# ---------------------------------------------------------------------------
# MinIO upload via disposable mc container
# ---------------------------------------------------------------------------
mc_cmd() {
    docker run --rm --network cri-backend \
        -v "${BACKUP_BASE}:/backups" \
        -e "MC_HOST_cri=http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio:9000" \
        minio/mc "$@"
}

mc_upload() {
    local local_file="$1"
    local remote_path="$2"  # e.g. cri-backups/postgres/daily/2026-04-03/

    # Convert absolute path to /backups/ relative path for the container
    local container_path="${local_file/#${BACKUP_BASE}/\/backups}"

    mc_cmd cp "${container_path}" "cri/${remote_path}"
    if [[ $? -ne 0 ]]; then
        log_error "MinIO upload failed: $(basename "${local_file}") → ${remote_path}"
        return 4
    fi
    log_info "Uploaded to MinIO: $(basename "${local_file}") → ${remote_path}"
}

mc_ensure_bucket() {
    mc_cmd mb --ignore-existing "cri/${BACKUP_BUCKET}"
}

# ---------------------------------------------------------------------------
# Retention pruning
# ---------------------------------------------------------------------------
prune_local() {
    local dir="$1"
    local max_age_days="$2"
    if [[ ! -d "${dir}" ]]; then
        return 0
    fi
    local count
    count=$(find "${dir}" -mindepth 1 -maxdepth 1 -type d -mtime "+${max_age_days}" | wc -l)
    if [[ "${count}" -gt 0 ]]; then
        find "${dir}" -mindepth 1 -maxdepth 1 -type d -mtime "+${max_age_days}" -exec rm -rf {} +
        log_info "Pruned ${count} local entries older than ${max_age_days} days in ${dir}"
    fi
}

prune_minio() {
    local prefix="$1"        # e.g. cri-backups/postgres/daily/
    local max_age_days="$2"
    local cutoff_date
    cutoff_date=$(date -d "-${max_age_days} days" +%Y-%m-%d 2>/dev/null || \
                  date -v-"${max_age_days}"d +%Y-%m-%d 2>/dev/null)

    # List directories in the prefix and remove those older than cutoff
    mc_cmd ls "cri/${prefix}" 2>/dev/null | while read -r line; do
        local dir_date
        dir_date=$(echo "${line}" | awk '{print $NF}' | tr -d '/')
        # Only process date-formatted directories (YYYY-MM-DD)
        if [[ "${dir_date}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "${dir_date}" < "${cutoff_date}" ]]; then
            mc_cmd rm --recursive --force "cri/${prefix}${dir_date}/"
            log_info "Pruned MinIO: ${prefix}${dir_date}/"
        fi
    done
}

prune_minio_monthly() {
    local prefix="$1"          # e.g. cri-backups/postgres/monthly/
    local max_months="$2"
    local cutoff_date
    cutoff_date=$(date -d "-${max_months} months" +%Y-%m 2>/dev/null || \
                  date -v-"${max_months}"m +%Y-%m 2>/dev/null)

    mc_cmd ls "cri/${prefix}" 2>/dev/null | while read -r line; do
        local dir_month
        dir_month=$(echo "${line}" | awk '{print $NF}' | tr -d '/')
        if [[ "${dir_month}" =~ ^[0-9]{4}-[0-9]{2}$ ]] && [[ "${dir_month}" < "${cutoff_date}" ]]; then
            mc_cmd rm --recursive --force "cri/${prefix}${dir_month}/"
            log_info "Pruned MinIO monthly: ${prefix}${dir_month}/"
        fi
    done
}

# ---------------------------------------------------------------------------
# Tenant enumeration
# ---------------------------------------------------------------------------
list_tenants() {
    docker compose -f "${DEPLOY_DIR}/${COMPOSE_FILE}" exec -T postgres \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A \
        -c "SELECT slug FROM public.tenants WHERE status = 'active' ORDER BY slug;"
}

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
is_last_of_month() {
    local tomorrow
    tomorrow=$(date -d "+1 day" +%d 2>/dev/null || date -v+1d +%d 2>/dev/null)
    [[ "${tomorrow}" == "01" ]]
}

# ---------------------------------------------------------------------------
# Disk space check
# ---------------------------------------------------------------------------
check_disk_space() {
    local min_gb="${1:-10}"
    local backup_avail_kb
    backup_avail_kb=$(df -k "${BACKUP_BASE}" | tail -1 | awk '{print $4}')
    local avail_gb=$((backup_avail_kb / 1048576))
    if [[ "${avail_gb}" -lt "${min_gb}" ]]; then
        log_warn "Low disk space: ${avail_gb}GB available (minimum ${min_gb}GB recommended)"
        return 1
    fi
    log_info "Disk space OK: ${avail_gb}GB available"
}

# ---------------------------------------------------------------------------
# Docker compose helper
# ---------------------------------------------------------------------------
dc() {
    docker compose -f "${DEPLOY_DIR}/${COMPOSE_FILE}" "$@"
}

# ---------------------------------------------------------------------------
# Health check (reused from deploy.sh pattern)
# ---------------------------------------------------------------------------
wait_for_health() {
    local url="${1:-http://localhost:8000/api/v1/health}"
    local max_retries="${2:-30}"
    local interval="${3:-5}"

    for i in $(seq 1 "${max_retries}"); do
        local status
        status=$(curl -sf "${url}" 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unreachable")

        if [[ "${status}" == "healthy" || "${status}" == "degraded" ]]; then
            log_info "Health check PASSED: ${status}"
            return 0
        fi
        log_info "Health check attempt ${i}/${max_retries}: ${status}"
        sleep "${interval}"
    done

    log_error "Health check failed after ${max_retries} attempts"
    return 1
}

# ---------------------------------------------------------------------------
# Initialization (called after sourcing)
# ---------------------------------------------------------------------------
init_backup() {
    mkdir -p "${LOG_DIR}"
    load_env
    check_disk_space || true
    log_info "=== ${SCRIPT_NAME} started ==="
}
