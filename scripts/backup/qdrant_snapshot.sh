#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Qdrant Weekly Snapshot
# Execution : cron hebdomadaire dimanche 03h00 (Africa/Casablanca)
# Snapshots toutes les collections kb_{tenant} via REST API
# Retention : 4 hebdomadaires + 3 mensuels
#
# Exit codes:
#   0 = success
#   1 = lock contention
#   2 = snapshot failure
#   3 = encryption failure
#   4 = MinIO upload failure
# =============================================================================

set -euo pipefail

SCRIPT_NAME="qdrant_snapshot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

QDRANT_CONTAINER="cri-qdrant"
QDRANT_API="http://localhost:6333"

# ---------------------------------------------------------------------------
# Qdrant helpers (run inside the container via docker exec)
# ---------------------------------------------------------------------------
qdrant_api() {
    local method="$1"
    local path="$2"
    shift 2
    docker exec "${QDRANT_CONTAINER}" wget -qO- \
        --method="${method}" \
        "${QDRANT_API}${path}" "$@" 2>/dev/null
}

list_collections() {
    docker exec "${QDRANT_CONTAINER}" wget -qO- "${QDRANT_API}/collections" | \
        python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data.get('result', {}).get('collections', []):
    print(c['name'])
"
}

create_snapshot() {
    local collection="$1"
    docker exec "${QDRANT_CONTAINER}" wget -qO- \
        --post-data='' \
        "${QDRANT_API}/collections/${collection}/snapshots" | \
        python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data['result']['name'])
"
}

download_snapshot() {
    local collection="$1"
    local snapshot_name="$2"
    local output_path="$3"

    # Download inside container to /tmp, then docker cp out
    docker exec "${QDRANT_CONTAINER}" wget -qO "/tmp/${snapshot_name}" \
        "${QDRANT_API}/collections/${collection}/snapshots/${snapshot_name}/download"
    docker cp "${QDRANT_CONTAINER}:/tmp/${snapshot_name}" "${output_path}"
    docker exec "${QDRANT_CONTAINER}" rm -f "/tmp/${snapshot_name}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    init_backup
    acquire_lock || exit 1

    local backup_dir="${BACKUP_BASE}/qdrant/${TODAY}"
    local start_time
    start_time=$(date +%s)

    mkdir -p "${backup_dir}"

    # --- Phase 1: List collections ------------------------------------------
    log_info "Listing Qdrant collections..."
    local collections
    collections=$(list_collections)

    if [[ -z "${collections}" ]]; then
        log_warn "No Qdrant collections found. Nothing to snapshot."
        log_info "=== Qdrant snapshot complete (no collections) ==="
        exit 0
    fi

    local collection_count
    collection_count=$(echo "${collections}" | wc -l)
    log_info "Found ${collection_count} collections"

    # --- Phase 2: Snapshot each collection ----------------------------------
    local snapshot_count=0
    while IFS= read -r collection; do
        [[ -z "${collection}" ]] && continue
        log_info "Snapshotting collection: ${collection}..."

        local snapshot_name
        snapshot_name=$(create_snapshot "${collection}")
        if [[ -z "${snapshot_name}" ]]; then
            log_error "Failed to create snapshot for ${collection}"
            exit 2
        fi
        log_info "  Snapshot created: ${snapshot_name}"

        download_snapshot "${collection}" "${snapshot_name}" \
            "${backup_dir}/${collection}_${snapshot_name}"
        log_info "  Downloaded: ${collection}_${snapshot_name}"

        snapshot_count=$((snapshot_count + 1))
    done <<< "${collections}"

    log_info "Snapshotted ${snapshot_count}/${collection_count} collections"

    # --- Phase 3: Tar all snapshots -----------------------------------------
    local tar_file="${BACKUP_BASE}/qdrant/qdrant_snapshot_${TIMESTAMP}.tar.gz"
    log_info "Creating archive..."
    tar -czf "${tar_file}" -C "${backup_dir}" .
    local tar_size
    tar_size=$(du -h "${tar_file}" | awk '{print $1}')
    log_info "Archive created: ${tar_size}"

    # --- Phase 4: Checksum + encrypt ----------------------------------------
    write_checksum "${tar_file}"
    log_info "Encrypting archive..."
    encrypt_file "${tar_file}" || exit 3
    local encrypted_file="${tar_file}.gpg"
    write_checksum "${encrypted_file}"

    # --- Phase 5: Upload to MinIO -------------------------------------------
    log_info "Uploading to MinIO..."
    mc_ensure_bucket
    mc_upload "${encrypted_file}" "${BACKUP_BUCKET}/qdrant/weekly/${TODAY}/" || exit 4
    mc_upload "${encrypted_file}.sha256" "${BACKUP_BUCKET}/qdrant/weekly/${TODAY}/" || exit 4
    mc_upload "${tar_file}.sha256" "${BACKUP_BUCKET}/qdrant/weekly/${TODAY}/" || exit 4

    # --- Phase 6: Monthly retention copy ------------------------------------
    if is_last_of_month; then
        log_info "Last day of month — creating monthly retention copy..."
        mc_cmd cp --recursive \
            "cri/${BACKUP_BUCKET}/qdrant/weekly/${TODAY}/" \
            "cri/${BACKUP_BUCKET}/qdrant/monthly/${YEAR}-${MONTH}/"
        log_info "Monthly copy created: ${YEAR}-${MONTH}"
    fi

    # --- Phase 7: Retention pruning -----------------------------------------
    log_info "Pruning old snapshots..."

    # Local: keep 14 days
    prune_local "${BACKUP_BASE}/qdrant" 14

    # MinIO weekly: keep 4 weeks (28 days)
    prune_minio "${BACKUP_BUCKET}/qdrant/weekly/" 28

    # MinIO monthly: keep 3 months
    prune_minio_monthly "${BACKUP_BUCKET}/qdrant/monthly/" 3

    # Clean up uncompressed snapshot directory
    rm -rf "${backup_dir}"

    # --- Phase 8: Summary ---------------------------------------------------
    local end_time duration
    end_time=$(date +%s)
    duration=$(( end_time - start_time ))
    local encrypted_size
    encrypted_size=$(du -h "${encrypted_file}" | awk '{print $1}')

    log_info "=== Qdrant snapshot complete ==="
    log_info "  Collections: ${snapshot_count}"
    log_info "  File: $(basename "${encrypted_file}")"
    log_info "  Size: ${encrypted_size}"
    log_info "  Duration: ${duration}s"
}

main "$@"
