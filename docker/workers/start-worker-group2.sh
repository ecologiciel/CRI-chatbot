#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — ARQ Worker Group 2
# Vector-DB-heavy workers: ingestion, learning, archive
# Usage: bash /app/scripts/start-worker-group2.sh
# =============================================================================
set -euo pipefail

PIDS=()

cleanup() {
    echo "[worker-group2] Received shutdown signal, stopping all workers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait
    echo "[worker-group2] All workers stopped."
}

trap cleanup SIGTERM SIGINT

echo "[worker-group2] Starting ingestion worker..."
arq app.workers.ingestion.WorkerSettings &
PIDS+=($!)

echo "[worker-group2] Starting learning worker..."
arq app.workers.learning.WorkerSettings &
PIDS+=($!)

echo "[worker-group2] Starting archive worker..."
arq app.workers.archive.WorkerSettings &
PIDS+=($!)

echo "[worker-group2] All 3 workers started (PIDs: ${PIDS[*]})"

# Wait for any child to exit; if one dies unexpectedly, stop all and exit
wait -n
EXIT_CODE=$?
echo "[worker-group2] A worker exited with code $EXIT_CODE, shutting down..."
cleanup
exit "$EXIT_CODE"
