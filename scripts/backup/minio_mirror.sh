#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — MinIO Weekly Mirror
# Execution : cron hebdomadaire dimanche 04h00 (Africa/Casablanca)
# Mirror de tous les buckets tenant vers stockage local
# Retention : 4 derniers mirrors
#
# Exit codes:
#   0 = success
#   1 = lock contention
#   2 = mirror failure
#   3 = encryption failure
# =============================================================================

set -euo pipefail

SCRIPT_NAME="minio_mirror"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    init_backup
    acquire_lock || exit 1

    local mirror_dir="${BACKUP_BASE}/minio/${TODAY}"
    local archive_dir="${BACKUP_BASE}/minio/archives"
    local start_time
    start_time=$(date +%s)

    mkdir -p "${mirror_dir}" "${archive_dir}"

    # --- Phase 1: List tenant buckets ---------------------------------------
    log_info "Listing MinIO tenant buckets..."
    local buckets
    buckets=$(mc_cmd ls cri/ 2>/dev/null | awk '{print $NF}' | tr -d '/' | grep "^cri-" | grep -v "^${BACKUP_BUCKET}$" || true)

    if [[ -z "${buckets}" ]]; then
        log_warn "No tenant buckets found. Nothing to mirror."
        log_info "=== MinIO mirror complete (no buckets) ==="
        exit 0
    fi

    local bucket_count
    bucket_count=$(echo "${buckets}" | wc -l)
    log_info "Found ${bucket_count} tenant buckets"

    # --- Phase 2: Mirror each bucket ---------------------------------------
    local total_files=0
    while IFS= read -r bucket; do
        [[ -z "${bucket}" ]] && continue
        log_info "Mirroring bucket: ${bucket}..."

        local bucket_dir="${mirror_dir}/${bucket}"
        mkdir -p "${bucket_dir}"

        # mc mirror from MinIO to local via container with volume mount
        mc_cmd mirror --overwrite "cri/${bucket}" "/backups/minio/${TODAY}/${bucket}/" 2>&1 | \
            tail -1 || true

        local file_count
        file_count=$(find "${bucket_dir}" -type f 2>/dev/null | wc -l)
        total_files=$((total_files + file_count))
        log_info "  Mirrored ${file_count} files from ${bucket}"
    done <<< "${buckets}"

    log_info "Total files mirrored: ${total_files}"

    # --- Phase 3: SHA-256 manifest ------------------------------------------
    log_info "Generating SHA-256 manifest..."
    local manifest="${mirror_dir}/manifest.sha256"
    find "${mirror_dir}" -type f -not -name "manifest.sha256" -exec sha256sum {} \; > "${manifest}"
    local manifest_lines
    manifest_lines=$(wc -l < "${manifest}")
    log_info "Manifest: ${manifest_lines} entries"

    # --- Phase 4: Archive (tar + encrypt) -----------------------------------
    local tar_file="${archive_dir}/minio_mirror_${TIMESTAMP}.tar.gz"
    log_info "Creating archive..."
    tar -czf "${tar_file}" -C "${mirror_dir}" .
    local tar_size
    tar_size=$(du -h "${tar_file}" | awk '{print $1}')
    log_info "Archive created: ${tar_size}"

    write_checksum "${tar_file}"
    log_info "Encrypting archive..."
    encrypt_file "${tar_file}" || exit 3
    local encrypted_file="${tar_file}.gpg"
    write_checksum "${encrypted_file}"

    # NOTE: Do NOT upload the archive back to MinIO — that would be circular.
    # The encrypted archive stays local at ${archive_dir}.
    log_info "Archive stored locally (not uploaded to MinIO to avoid circular backup)"

    # --- Phase 5: Retention pruning -----------------------------------------
    log_info "Pruning old mirrors..."

    # Local mirrors: keep 4 weekly (28 days)
    prune_local "${BACKUP_BASE}/minio" 28

    # Local archives: keep 4 most recent
    local archive_count
    archive_count=$(find "${archive_dir}" -name "*.gpg" -type f 2>/dev/null | wc -l)
    if [[ "${archive_count}" -gt 4 ]]; then
        local to_remove=$((archive_count - 4))
        find "${archive_dir}" -name "*.gpg" -type f -printf '%T+ %p\n' | \
            sort | head -n "${to_remove}" | awk '{print $2}' | while read -r old_file; do
            rm -f "${old_file}" "${old_file}.sha256"
            log_info "Pruned archive: $(basename "${old_file}")"
        done
    fi

    # --- Phase 6: Summary ---------------------------------------------------
    local end_time duration
    end_time=$(date +%s)
    duration=$(( end_time - start_time ))

    log_info "=== MinIO mirror complete ==="
    log_info "  Buckets: ${bucket_count}"
    log_info "  Files: ${total_files}"
    log_info "  Archive: $(basename "${encrypted_file}")"
    log_info "  Duration: ${duration}s"
}

main "$@"
