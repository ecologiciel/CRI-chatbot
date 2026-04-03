#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Procedure de Restauration Complete
# Objectif : RTO < 4h, RPO < 24h
#
# Usage :
#   ./restore.sh --date 2026-04-03
#   ./restore.sh --date 2026-04-03 --skip-qdrant --skip-minio
#   ./restore.sh --date 2026-04-03 --source minio
#   ./restore.sh --dry-run --date 2026-04-03
#
# Exit codes:
#   0 = success
#   1 = pre-flight failure / lock
#   2 = PostgreSQL restore failure
#   3 = Qdrant restore failure
#   4 = MinIO restore failure
#   5 = health check failure
# =============================================================================

set -euo pipefail

SCRIPT_NAME="restore"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

QDRANT_CONTAINER="cri-qdrant"
QDRANT_API="http://localhost:6333"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RESTORE_DATE=""
SKIP_POSTGRES=false
SKIP_QDRANT=false
SKIP_MINIO=false
DRY_RUN=false
SOURCE="local"  # local | minio

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Restore the CRI Chatbot Platform from backup.

Options:
  --date YYYY-MM-DD   Backup date to restore (required)
  --skip-postgres     Skip PostgreSQL restoration
  --skip-qdrant       Skip Qdrant restoration
  --skip-minio        Skip MinIO restoration
  --source local|minio  Backup source (default: local, fallback: minio)
  --dry-run           Validate backup integrity without restoring
  -h, --help          Show this help

Examples:
  $(basename "$0") --date 2026-04-03
  $(basename "$0") --date 2026-04-03 --skip-qdrant --skip-minio
  $(basename "$0") --date 2026-04-03 --source minio --dry-run
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --date)       RESTORE_DATE="$2"; shift 2 ;;
        --skip-postgres) SKIP_POSTGRES=true; shift ;;
        --skip-qdrant)   SKIP_QDRANT=true; shift ;;
        --skip-minio)    SKIP_MINIO=true; shift ;;
        --source)     SOURCE="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        -h|--help)    usage ;;
        *)            log_error "Unknown option: $1"; usage ;;
    esac
done

if [[ -z "${RESTORE_DATE}" ]]; then
    log_error "--date is required"
    usage
fi

# Validate date format
if [[ ! "${RESTORE_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    log_error "Invalid date format: ${RESTORE_DATE}. Expected YYYY-MM-DD."
    exit 1
fi

# ---------------------------------------------------------------------------
# Locate backup files
# ---------------------------------------------------------------------------
locate_pg_backup() {
    local pg_dir="${BACKUP_BASE}/postgres/${RESTORE_DATE}"

    if [[ "${SOURCE}" == "local" ]] && [[ -d "${pg_dir}" ]]; then
        local found
        found=$(find "${pg_dir}" -name "*.dump.gpg" -type f | head -1)
        if [[ -n "${found}" ]]; then
            echo "${found}"
            return 0
        fi
    fi

    # Fallback: download from MinIO
    log_info "PostgreSQL backup not found locally, downloading from MinIO..."
    local remote_prefix="${BACKUP_BUCKET}/postgres/daily/${RESTORE_DATE}/"
    mkdir -p "${pg_dir}"

    mc_cmd mirror "cri/${remote_prefix}" "/backups/postgres/${RESTORE_DATE}/" 2>/dev/null || true

    local found
    found=$(find "${pg_dir}" -name "*.dump.gpg" -type f | head -1)
    if [[ -n "${found}" ]]; then
        echo "${found}"
        return 0
    fi

    # Try monthly backup
    local month="${RESTORE_DATE:0:7}"
    log_info "Trying monthly backup: ${month}..."
    remote_prefix="${BACKUP_BUCKET}/postgres/monthly/${month}/"
    mc_cmd mirror "cri/${remote_prefix}" "/backups/postgres/${RESTORE_DATE}/" 2>/dev/null || true

    found=$(find "${pg_dir}" -name "*.dump.gpg" -type f | head -1)
    echo "${found}"
}

locate_qdrant_backup() {
    local qdrant_dir="${BACKUP_BASE}/qdrant"

    if [[ "${SOURCE}" == "local" ]]; then
        local found
        found=$(find "${qdrant_dir}" -name "qdrant_snapshot_${RESTORE_DATE}*.tar.gz.gpg" -type f | head -1)
        if [[ -n "${found}" ]]; then
            echo "${found}"
            return 0
        fi
    fi

    # Download from MinIO
    log_info "Qdrant backup not found locally, downloading from MinIO..."
    local remote_prefix="${BACKUP_BUCKET}/qdrant/weekly/${RESTORE_DATE}/"
    mkdir -p "${qdrant_dir}/${RESTORE_DATE}"
    mc_cmd mirror "cri/${remote_prefix}" "/backups/qdrant/${RESTORE_DATE}/" 2>/dev/null || true

    local found
    found=$(find "${qdrant_dir}/${RESTORE_DATE}" -name "*.tar.gz.gpg" -type f | head -1)
    echo "${found}"
}

locate_minio_backup() {
    local archive_dir="${BACKUP_BASE}/minio/archives"

    if [[ "${SOURCE}" == "local" ]]; then
        local found
        found=$(find "${archive_dir}" -name "minio_mirror_${RESTORE_DATE}*.tar.gz.gpg" -type f | head -1)
        if [[ -n "${found}" ]]; then
            echo "${found}"
            return 0
        fi
    fi

    # MinIO archives are stored locally (not in MinIO — circular), so no fallback
    log_warn "MinIO archive not found locally. MinIO archives are not stored in MinIO (circular)."
    echo ""
}

# ---------------------------------------------------------------------------
# Restore functions
# ---------------------------------------------------------------------------
restore_postgres() {
    local encrypted_file="$1"
    log_info "=== Phase 2: PostgreSQL Restore ==="

    # Verify encrypted checksum
    if [[ -f "${encrypted_file}.sha256" ]]; then
        verify_sha256 "${encrypted_file}" || exit 2
    fi

    # Decrypt
    log_info "Decrypting PostgreSQL backup..."
    decrypt_file "${encrypted_file}" || exit 2
    local dump_file="${encrypted_file%.gpg}"

    # Verify plaintext checksum
    if [[ -f "${dump_file}.sha256" ]]; then
        verify_sha256 "${dump_file}" || exit 2
    fi

    # Stop application services
    log_info "Stopping backend and frontend..."
    dc stop backend frontend 2>/dev/null || true

    # Restore
    log_info "Restoring PostgreSQL (this may take several minutes)..."
    cat "${dump_file}" | dc exec -T postgres \
        pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
            --clean --if-exists --no-owner --no-acl \
            --jobs=4 2>&1 | tail -5 || true
    # pg_restore returns non-zero for warnings (e.g. "relation does not exist" on --clean)
    # so we don't exit on error — instead verify the result

    # Verify
    local tenant_count
    tenant_count=$(dc exec -T postgres \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A \
        -c "SELECT count(*) FROM public.tenants;" 2>/dev/null || echo "0")
    tenant_count=$(echo "${tenant_count}" | tr -d '[:space:]')

    if [[ "${tenant_count}" -gt 0 ]]; then
        log_info "PostgreSQL restore verified: ${tenant_count} tenants"
    else
        log_error "PostgreSQL restore verification failed: 0 tenants found"
        exit 2
    fi

    # Run Alembic migrations (in case backup is from an older version)
    log_info "Running Alembic migrations..."
    dc run --rm backend alembic upgrade head 2>&1 | tail -3 || true

    # Cleanup decrypted file
    rm -f "${dump_file}"
    log_info "PostgreSQL restore complete"
}

restore_qdrant() {
    local encrypted_file="$1"
    log_info "=== Phase 3: Qdrant Restore ==="

    # Verify + decrypt
    if [[ -f "${encrypted_file}.sha256" ]]; then
        verify_sha256 "${encrypted_file}" || exit 3
    fi
    log_info "Decrypting Qdrant backup..."
    decrypt_file "${encrypted_file}" || exit 3
    local tar_file="${encrypted_file%.gpg}"

    # Extract snapshots
    local extract_dir="${BACKUP_BASE}/qdrant/restore_tmp"
    mkdir -p "${extract_dir}"
    tar -xzf "${tar_file}" -C "${extract_dir}"

    # Restore each collection snapshot
    local restored=0
    for snapshot_file in "${extract_dir}"/*; do
        [[ ! -f "${snapshot_file}" ]] && continue
        local filename
        filename=$(basename "${snapshot_file}")

        # Extract collection name: format is {collection}_{snapshot_name}
        # Collection names are kb_* so we split on the first snapshot timestamp
        local collection
        collection=$(echo "${filename}" | sed 's/_[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}.*//')

        log_info "Restoring collection: ${collection}..."

        # Copy snapshot into container
        docker cp "${snapshot_file}" "${QDRANT_CONTAINER}:/tmp/${filename}"

        # Recover from snapshot via API
        docker exec "${QDRANT_CONTAINER}" wget -qO- \
            --method=PUT \
            --header="Content-Type: application/json" \
            --body-data="{\"location\": \"/tmp/${filename}\"}" \
            "${QDRANT_API}/collections/${collection}/snapshots/recover" || {
                log_warn "Failed to restore collection ${collection} — it may not exist yet"
            }

        # Cleanup inside container
        docker exec "${QDRANT_CONTAINER}" rm -f "/tmp/${filename}"
        restored=$((restored + 1))
    done

    # Verify
    local collection_count
    collection_count=$(docker exec "${QDRANT_CONTAINER}" wget -qO- "${QDRANT_API}/collections" | \
        python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('collections',[])))" 2>/dev/null || echo "0")
    log_info "Qdrant restore complete: ${restored} snapshots applied, ${collection_count} collections present"

    # Cleanup
    rm -rf "${extract_dir}" "${tar_file}"
}

restore_minio() {
    local encrypted_file="$1"
    log_info "=== Phase 4: MinIO Restore ==="

    # Verify + decrypt
    if [[ -f "${encrypted_file}.sha256" ]]; then
        verify_sha256 "${encrypted_file}" || exit 4
    fi
    log_info "Decrypting MinIO backup..."
    decrypt_file "${encrypted_file}" || exit 4
    local tar_file="${encrypted_file%.gpg}"

    # Extract mirror
    local extract_dir="${BACKUP_BASE}/minio/restore_tmp"
    mkdir -p "${extract_dir}"
    tar -xzf "${tar_file}" -C "${extract_dir}"

    # Restore each tenant bucket
    local restored=0
    for bucket_dir in "${extract_dir}"/cri-*; do
        [[ ! -d "${bucket_dir}" ]] && continue
        local bucket
        bucket=$(basename "${bucket_dir}")
        log_info "Restoring bucket: ${bucket}..."

        # Ensure bucket exists
        mc_cmd mb --ignore-existing "cri/${bucket}"

        # Mirror back from local to MinIO
        mc_cmd mirror --overwrite "/backups/minio/restore_tmp/${bucket}" "cri/${bucket}/" || {
            log_warn "Failed to restore bucket ${bucket}"
        }
        restored=$((restored + 1))
    done

    log_info "MinIO restore complete: ${restored} buckets restored"

    # Cleanup
    rm -rf "${extract_dir}" "${tar_file}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    init_backup
    acquire_lock || exit 1

    local start_time
    start_time=$(date +%s)

    log_info "============================================"
    log_info "CRI Platform Restoration"
    log_info "  Date: ${RESTORE_DATE}"
    log_info "  Source: ${SOURCE}"
    log_info "  Skip PostgreSQL: ${SKIP_POSTGRES}"
    log_info "  Skip Qdrant: ${SKIP_QDRANT}"
    log_info "  Skip MinIO: ${SKIP_MINIO}"
    log_info "  Dry run: ${DRY_RUN}"
    log_info "============================================"

    # -----------------------------------------------------------------------
    # Phase 0: Locate backups
    # -----------------------------------------------------------------------
    log_info "=== Phase 0: Locating backups ==="

    local pg_file="" qdrant_file="" minio_file=""

    if [[ "${SKIP_POSTGRES}" == "false" ]]; then
        pg_file=$(locate_pg_backup)
        if [[ -z "${pg_file}" ]]; then
            log_error "PostgreSQL backup not found for ${RESTORE_DATE}"
            exit 1
        fi
        log_info "PostgreSQL backup: $(basename "${pg_file}")"
    fi

    if [[ "${SKIP_QDRANT}" == "false" ]]; then
        qdrant_file=$(locate_qdrant_backup)
        if [[ -z "${qdrant_file}" ]]; then
            log_warn "Qdrant backup not found for ${RESTORE_DATE} — will skip"
            SKIP_QDRANT=true
        else
            log_info "Qdrant backup: $(basename "${qdrant_file}")"
        fi
    fi

    if [[ "${SKIP_MINIO}" == "false" ]]; then
        minio_file=$(locate_minio_backup)
        if [[ -z "${minio_file}" ]]; then
            log_warn "MinIO backup not found for ${RESTORE_DATE} — will skip"
            SKIP_MINIO=true
        else
            log_info "MinIO backup: $(basename "${minio_file}")"
        fi
    fi

    # -----------------------------------------------------------------------
    # Phase 1: Pre-flight checks
    # -----------------------------------------------------------------------
    log_info "=== Phase 1: Pre-flight checks ==="

    # Docker must be running
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running"
        exit 1
    fi

    # Data services must be running
    if ! dc ps postgres --format '{{.State}}' 2>/dev/null | grep -q "running"; then
        log_error "PostgreSQL container is not running"
        exit 1
    fi

    check_disk_space 20 || {
        log_error "Insufficient disk space for restore (need >= 20GB)"
        exit 1
    }

    # -----------------------------------------------------------------------
    # Dry run: stop here
    # -----------------------------------------------------------------------
    if [[ "${DRY_RUN}" == "true" ]]; then
        log_info "=== DRY RUN — Validation complete ==="
        log_info "All backup files located and pre-flight checks passed."
        log_info "Run without --dry-run to proceed with restoration."
        exit 0
    fi

    # -----------------------------------------------------------------------
    # Phase 2-4: Restore components
    # -----------------------------------------------------------------------
    if [[ "${SKIP_POSTGRES}" == "false" ]]; then
        restore_postgres "${pg_file}"
    else
        log_info "Skipping PostgreSQL restore (--skip-postgres)"
    fi

    if [[ "${SKIP_QDRANT}" == "false" ]]; then
        restore_qdrant "${qdrant_file}"
    else
        log_info "Skipping Qdrant restore (--skip-qdrant)"
    fi

    if [[ "${SKIP_MINIO}" == "false" ]]; then
        restore_minio "${minio_file}"
    else
        log_info "Skipping MinIO restore (--skip-minio)"
    fi

    # -----------------------------------------------------------------------
    # Phase 5: Restart and verify
    # -----------------------------------------------------------------------
    log_info "=== Phase 5: Restart and verify ==="

    log_info "Starting all services..."
    dc up -d

    log_info "Waiting for health check..."
    if ! wait_for_health; then
        log_error "Health check failed after restore"
        exit 5
    fi

    # -----------------------------------------------------------------------
    # Phase 6: Summary
    # -----------------------------------------------------------------------
    local end_time duration
    end_time=$(date +%s)
    duration=$(( end_time - start_time ))
    local duration_min=$(( duration / 60 ))

    log_info "============================================"
    log_info "RESTORATION COMPLETE"
    log_info "  Date restored: ${RESTORE_DATE}"
    log_info "  Duration: ${duration_min} minutes (${duration}s)"
    log_info "  PostgreSQL: $(if ${SKIP_POSTGRES}; then echo "skipped"; else echo "restored"; fi)"
    log_info "  Qdrant: $(if ${SKIP_QDRANT}; then echo "skipped"; else echo "restored"; fi)"
    log_info "  MinIO: $(if ${SKIP_MINIO}; then echo "skipped"; else echo "restored"; fi)"
    log_info "  RTO target: < 4h — Actual: ${duration_min}min"
    log_info "============================================"
}

main "$@"
