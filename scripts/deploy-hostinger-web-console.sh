#!/usr/bin/env bash
# Deploy from the VPS Web Console after .env.demo has been securely created.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
COMPOSE=(docker compose --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)

cd "$DEPLOY_DIR"
test -f .env.demo
command -v flock >/dev/null
[[ ! -L .kms-rotation.lock ]] || { echo "Unsafe maintenance lock." >&2; exit 1; }
exec 8> .kms-rotation.lock
chmod 600 .kms-rotation.lock
flock -x -n 8 || { echo "Backup or KMS maintenance in progress." >&2; exit 1; }
[[ ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || { echo "Unfinished or unsafe KMS maintenance." >&2; exit 1; }
ensure_no_durable_workers() {
  local profile_running
  profile_running=$("${COMPOSE[@]}" --profile whatsapp-durable --profile dossier-import --profile dossier-outbox --profile agent-replies ps --status running --services)
  if grep -Eq '^(whatsapp-inbox-worker|dossier-import-worker|dossier-outbox-worker|agent-reply-worker)$' <<< "$profile_running"; then
    echo "A durable worker is running; use a coordinated maintenance procedure." >&2
    return 1
  fi
}
ensure_no_durable_workers

"${COMPOSE[@]}" build backend frontend-demo frontend-admin
ensure_no_durable_workers
"${COMPOSE[@]}" up -d --force-recreate

echo "Waiting for the API to become healthy..."
for attempt in $(seq 1 36); do
  if "${COMPOSE[@]}" exec -T backend python -m app.scripts.healthcheck; then
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done

"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=100 >&2
exit 1
