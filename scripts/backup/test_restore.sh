#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Test de Restauration (Staging)
# Execution recommandee : trimestrielle
# Verifie que le PRA fonctionne reellement en restaurant sur le VPS staging
#
# Usage :
#   ./test_restore.sh                           # Latest backup, local staging
#   ./test_restore.sh --date 2026-04-03         # Specific date
#   ./test_restore.sh --remote staging.cri.ma   # Remote staging VPS
#
# Exit codes:
#   0 = all smoke tests passed
#   1 = pre-flight / setup failure
#   2 = restore failure
#   3 = smoke test failure
# =============================================================================

set -euo pipefail

SCRIPT_NAME="test_restore"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RESTORE_DATE=""
REMOTE_HOST=""
REPORT_DIR="${LOG_DIR}/restore-tests"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --date)       RESTORE_DATE="$2"; shift 2 ;;
        --remote)     REMOTE_HOST="$2"; shift 2 ;;
        --report-dir) REPORT_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--date YYYY-MM-DD] [--remote HOST] [--report-dir DIR]"
            exit 0
            ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Find latest backup date if not specified
# ---------------------------------------------------------------------------
find_latest_backup_date() {
    # Check local backups first
    local latest
    latest=$(find "${BACKUP_BASE}/postgres" -mindepth 1 -maxdepth 1 -type d -name "20*" | \
        sort -r | head -1 | xargs -I{} basename {} 2>/dev/null || true)

    if [[ -n "${latest}" ]]; then
        echo "${latest}"
        return 0
    fi

    # Check MinIO
    latest=$(mc_cmd ls "cri/${BACKUP_BUCKET}/postgres/daily/" 2>/dev/null | \
        awk '{print $NF}' | tr -d '/' | sort -r | head -1 || true)
    echo "${latest}"
}

# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------
run_smoke_tests() {
    local passed=0
    local failed=0
    local results=""

    # Test 1: Health endpoint
    log_info "Smoke test: Health endpoint..."
    local health_status
    health_status=$(curl -sf "http://localhost:8000/api/v1/health" 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unreachable")
    if [[ "${health_status}" == "healthy" || "${health_status}" == "degraded" ]]; then
        log_info "  PASS: Health endpoint returned '${health_status}'"
        results+="| Health endpoint | PASS | Status: ${health_status} |\n"
        passed=$((passed + 1))
    else
        log_error "  FAIL: Health endpoint returned '${health_status}'"
        results+="| Health endpoint | FAIL | Status: ${health_status} |\n"
        failed=$((failed + 1))
    fi

    # Test 2: Tenant count
    log_info "Smoke test: Tenant count..."
    local tenant_count
    tenant_count=$(dc exec -T postgres \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A \
        -c "SELECT count(*) FROM public.tenants;" 2>/dev/null || echo "0")
    tenant_count=$(echo "${tenant_count}" | tr -d '[:space:]')
    if [[ "${tenant_count}" -gt 0 ]]; then
        log_info "  PASS: ${tenant_count} tenants found"
        results+="| Tenant count | PASS | ${tenant_count} tenants |\n"
        passed=$((passed + 1))
    else
        log_error "  FAIL: 0 tenants found"
        results+="| Tenant count | FAIL | 0 tenants |\n"
        failed=$((failed + 1))
    fi

    # Test 3: Qdrant collections
    log_info "Smoke test: Qdrant collections..."
    local collection_count
    collection_count=$(docker exec cri-qdrant wget -qO- "http://localhost:6333/collections" 2>/dev/null | \
        python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('collections',[])))" 2>/dev/null || echo "0")
    if [[ "${collection_count}" -gt 0 ]]; then
        log_info "  PASS: ${collection_count} Qdrant collections"
        results+="| Qdrant collections | PASS | ${collection_count} collections |\n"
        passed=$((passed + 1))
    else
        log_warn "  WARN: 0 Qdrant collections (may be expected if no KB data)"
        results+="| Qdrant collections | WARN | 0 collections |\n"
    fi

    # Test 4: MinIO buckets
    log_info "Smoke test: MinIO buckets..."
    local bucket_count
    bucket_count=$(mc_cmd ls cri/ 2>/dev/null | grep "cri-" | wc -l || echo "0")
    if [[ "${bucket_count}" -gt 0 ]]; then
        log_info "  PASS: ${bucket_count} MinIO buckets"
        results+="| MinIO buckets | PASS | ${bucket_count} buckets |\n"
        passed=$((passed + 1))
    else
        log_warn "  WARN: 0 MinIO tenant buckets (may be expected)"
        results+="| MinIO buckets | WARN | 0 buckets |\n"
    fi

    # Test 5: Backend container running
    log_info "Smoke test: Backend container..."
    local backend_state
    backend_state=$(dc ps backend --format '{{.State}}' 2>/dev/null || echo "unknown")
    if [[ "${backend_state}" == "running" ]]; then
        log_info "  PASS: Backend container running"
        results+="| Backend container | PASS | State: running |\n"
        passed=$((passed + 1))
    else
        log_error "  FAIL: Backend container state: ${backend_state}"
        results+="| Backend container | FAIL | State: ${backend_state} |\n"
        failed=$((failed + 1))
    fi

    # Return results
    echo "PASSED=${passed}"
    echo "FAILED=${failed}"
    echo "RESULTS=${results}"

    [[ "${failed}" -eq 0 ]]
}

# ---------------------------------------------------------------------------
# Generate report
# ---------------------------------------------------------------------------
generate_report() {
    local restore_date="$1"
    local duration_min="$2"
    local test_passed="$3"
    local test_failed="$4"
    local test_results="$5"
    local overall="$6"

    local report_file="${REPORT_DIR}/restore-test-${TODAY}.md"
    mkdir -p "${REPORT_DIR}"

    cat > "${report_file}" <<EOF
# PRA Restore Test Report — ${TODAY}

## Summary

| Parameter | Value |
|-----------|-------|
| Test date | ${TODAY} |
| Backup restored | ${restore_date} |
| Duration | ${duration_min} minutes |
| Overall result | **${overall}** |
| Tests passed | ${test_passed} |
| Tests failed | ${test_failed} |

## Smoke Test Results

| Test | Result | Details |
|------|--------|---------|
$(echo -e "${test_results}")

## Disk Usage

\`\`\`
$(df -h "${BACKUP_BASE}" | head -2)
\`\`\`

## Notes

- Restore source: ${SOURCE:-local}
- VPS: $(hostname 2>/dev/null || echo "unknown")
- Report generated by: scripts/backup/test_restore.sh
EOF

    log_info "Report generated: ${report_file}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    init_backup
    acquire_lock || exit 1

    local start_time
    start_time=$(date +%s)

    # Determine backup date
    if [[ -z "${RESTORE_DATE}" ]]; then
        log_info "No date specified, finding latest backup..."
        RESTORE_DATE=$(find_latest_backup_date)
        if [[ -z "${RESTORE_DATE}" ]]; then
            log_error "No backups found"
            exit 1
        fi
    fi
    log_info "Testing restore of backup: ${RESTORE_DATE}"

    # --- Phase 1: Execute restore -------------------------------------------
    log_info "=== Phase 1: Executing restore ==="

    local restore_cmd="${SCRIPT_DIR}/restore.sh --date ${RESTORE_DATE} --source ${SOURCE:-local}"

    if [[ -n "${REMOTE_HOST}" ]]; then
        log_info "Running restore on remote host: ${REMOTE_HOST}"
        ssh "${REMOTE_HOST}" "bash ${DEPLOY_DIR}/scripts/backup/restore.sh --date ${RESTORE_DATE} --source minio" || {
            log_error "Remote restore failed"
            exit 2
        }
    else
        log_info "Running restore locally..."
        bash "${restore_cmd}" || {
            log_error "Restore failed (exit code: $?)"
            exit 2
        }
    fi

    # --- Phase 2: Smoke tests -----------------------------------------------
    log_info "=== Phase 2: Running smoke tests ==="

    local test_output
    test_output=$(run_smoke_tests) || true

    local test_passed test_failed test_results
    test_passed=$(echo "${test_output}" | grep "^PASSED=" | cut -d= -f2)
    test_failed=$(echo "${test_output}" | grep "^FAILED=" | cut -d= -f2)
    test_results=$(echo "${test_output}" | grep "^RESULTS=" | cut -d= -f2-)

    local overall="PASS"
    if [[ "${test_failed}" -gt 0 ]]; then
        overall="FAIL"
    fi

    # --- Phase 3: Generate report -------------------------------------------
    local end_time duration duration_min
    end_time=$(date +%s)
    duration=$(( end_time - start_time ))
    duration_min=$(( duration / 60 ))

    generate_report "${RESTORE_DATE}" "${duration_min}" \
        "${test_passed}" "${test_failed}" "${test_results}" "${overall}"

    # --- Summary ------------------------------------------------------------
    log_info "============================================"
    log_info "RESTORE TEST: ${overall}"
    log_info "  Backup date: ${RESTORE_DATE}"
    log_info "  Duration: ${duration_min} minutes"
    log_info "  Tests: ${test_passed} passed, ${test_failed} failed"
    log_info "============================================"

    if [[ "${overall}" == "FAIL" ]]; then
        exit 3
    fi
}

main "$@"
