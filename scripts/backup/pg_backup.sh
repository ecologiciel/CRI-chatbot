#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — PostgreSQL Daily Backup
# Execution : cron quotidien 02h00 (Africa/Casablanca)
# Retention : 30 jours glissants + dernier jour de chaque mois (12 mois)
#
# Exit codes:
#   0 = success
#   1 = lock contention
#   2 = pg_dump failure
#   3 = encryption failure
#   4 = MinIO upload failure
# =============================================================================

set -euo pipefail

SCRIPT_NAME="pg_backup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    init_backup
    acquire_lock || exit 1

    local backup_dir="${BACKUP_BASE}/postgres/${TODAY}"
    local dump_file="${backup_dir}/cri_platform_${TIMESTAMP}.dump"
    local start_time
    start_time=$(date +%s)

    mkdir -p "${backup_dir}"

    # --- Phase 1: pg_dump ---------------------------------------------------
    log_info "Starting PostgreSQL dump..."
    if ! dc exec -T postgres \
        pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
            --format=custom --compress=9 --no-owner --no-acl \
        > "${dump_file}"; then
        log_error "pg_dump failed"
        exit 2
    fi

    local dump_size
    dump_size=$(du -h "${dump_file}" | awk '{print $1}')
    log_info "pg_dump complete: ${dump_size}"

    # --- Phase 2: Checksum (plaintext) --------------------------------------
    write_checksum "${dump_file}"

    # --- Phase 3: GPG encryption --------------------------------------------
    log_info "Encrypting backup..."
    encrypt_file "${dump_file}" || exit 3
    # dump_file is now removed, .gpg exists
    local encrypted_file="${dump_file}.gpg"

    # Checksum of encrypted file (for transfer integrity)
    write_checksum "${encrypted_file}"

    # --- Phase 4: Upload to MinIO -------------------------------------------
    log_info "Uploading to MinIO..."
    mc_ensure_bucket
    mc_upload "${encrypted_file}" "${BACKUP_BUCKET}/postgres/daily/${TODAY}/" || exit 4
    mc_upload "${encrypted_file}.sha256" "${BACKUP_BUCKET}/postgres/daily/${TODAY}/" || exit 4
    # Also upload the plaintext checksum (for post-decrypt verification)
    mc_upload "${dump_file}.sha256" "${BACKUP_BUCKET}/postgres/daily/${TODAY}/" || exit 4

    # --- Phase 5: Monthly retention copy ------------------------------------
    if is_last_of_month; then
        log_info "Last day of month — creating monthly retention copy..."
        mc_cmd cp --recursive \
            "cri/${BACKUP_BUCKET}/postgres/daily/${TODAY}/" \
            "cri/${BACKUP_BUCKET}/postgres/monthly/${YEAR}-${MONTH}/"
        log_info "Monthly copy created: ${YEAR}-${MONTH}"
    fi

    # --- Phase 6: Retention pruning -----------------------------------------
    log_info "Pruning old backups..."

    # Local: keep 7 days (save disk space, MinIO has the full retention)
    prune_local "${BACKUP_BASE}/postgres" 7

    # MinIO daily: keep RETENTION_DAILY_DAYS (default 30)
    prune_minio "${BACKUP_BUCKET}/postgres/daily/" "${RETENTION_DAILY_DAYS}"

    # MinIO monthly: keep RETENTION_MONTHLY_MONTHS (default 12)
    prune_minio_monthly "${BACKUP_BUCKET}/postgres/monthly/" "${RETENTION_MONTHLY_MONTHS}"

    # --- Phase 7: Summary ---------------------------------------------------
    local end_time duration
    end_time=$(date +%s)
    duration=$(( end_time - start_time ))
    local encrypted_size
    encrypted_size=$(du -h "${encrypted_file}" | awk '{print $1}')

    log_info "=== PostgreSQL backup complete ==="
    log_info "  File: $(basename "${encrypted_file}")"
    log_info "  Size: ${encrypted_size} (compressed+encrypted)"
    log_info "  Duration: ${duration}s"
    log_info "  Retention: daily=${RETENTION_DAILY_DAYS}d, monthly=${RETENTION_MONTHLY_MONTHS}m"
}

main "$@"
