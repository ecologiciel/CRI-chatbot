#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — ARQ Worker Group 1
# I/O-bound workers: import, notification, campaign, purge
# Usage: bash /app/scripts/start-worker-group1.sh
# =============================================================================
set -euo pipefail

PIDS=()

cleanup() {
    echo "[worker-group1] Received shutdown signal, stopping all workers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait
    echo "[worker-group1] All workers stopped."
}

trap cleanup SIGTERM SIGINT

echo "[worker-group1] Starting import_dossier worker..."
arq app.workers.import_dossier.WorkerSettings &
PIDS+=($!)

echo "[worker-group1] Starting notification worker..."
arq app.workers.notification.WorkerSettings &
PIDS+=($!)

echo "[worker-group1] Starting campaign worker..."
arq app.workers.campaign.WorkerSettings &
PIDS+=($!)

echo "[worker-group1] Starting purge worker..."
arq app.workers.purge.WorkerSettings &
PIDS+=($!)

echo "[worker-group1] All 4 workers started (PIDs: ${PIDS[*]})"

# Wait for any child to exit; if one dies unexpectedly, stop all and exit
wait -n
EXIT_CODE=$?
echo "[worker-group1] A worker exited with code $EXIT_CODE, shutting down..."
cleanup
exit "$EXIT_CODE"
