#!/usr/bin/env bash
# Add a previously tested relay image without restarting existing services.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_RELAY:?Tested relay image required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo 'Invalid project' >&2; exit 1; }
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || { echo 'Unsafe deployment paths' >&2; exit 1; }
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || { echo 'Unsafe KMS state' >&2; exit 1; }
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || { echo 'Unsafe backup state' >&2; exit 1; }
exec 8> .kms-rotation.lock
flock -x -n 8 || { echo 'KMS maintenance or backup in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"
flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected or modified source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
COMPOSE=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml --profile local-wa-relay)
backend_id=$("${COMPOSE[@]}" ps -q backend)
[[ -n "$backend_id" && "$(docker inspect -f '{{.State.Health.Status}}' "$backend_id")" == healthy ]] || { echo 'Backend unavailable' >&2; exit 1; }
"${COMPOSE[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert not s.whatsapp_tenant_webhook_enabled and not s.whatsapp_durable_inbox_enabled and s.webhook_proxy_shared_secret'
[[ -z "$("${COMPOSE[@]}" ps -aq whatsapp-relay)" ]] || { echo 'Relay already exists; refusing replacement' >&2; exit 1; }
relay_tag=$("${COMPOSE[@]}" --profile whatsapp-durable --profile agent-replies --profile dossier-import --profile dossier-outbox config --no-interpolate --format json | python3 -c '
import json, re, sys
services = json.load(sys.stdin)["services"]
tag = services["whatsapp-relay"]["image"]
if not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*", tag):
    raise SystemExit("Invalid relay image tag")
if any(service.get("image") == tag for name, service in services.items() if name != "whatsapp-relay"):
    raise SystemExit("Relay image tag conflicts with another service")
print(tag)
')
if docker image inspect "$relay_tag" >/dev/null 2>&1; then echo 'Relay tag already exists; refusing replacement' >&2; exit 1; fi
image=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_RELAY")
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid image identity' >&2; exit 1; }
started=0
rollback() {
  local rc=$?
  trap - ERR INT TERM
  if (( started )); then
    "${COMPOSE[@]}" stop -t 15 whatsapp-relay >&2 || true
  fi
  echo 'Relay deployment incomplete; inspect before retrying' >&2
  exit "$rc"
}
trap rollback ERR INT TERM
docker tag "$image" "$relay_tag"
started=1
"${COMPOSE[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 whatsapp-relay
relay_id=$("${COMPOSE[@]}" ps -q whatsapp-relay)
[[ -n "$relay_id" && "$(docker inspect -f '{{.Image}}' "$relay_id")" == "$image" ]] || { echo 'Unexpected relay image' >&2; false; }
[[ "$(docker inspect -f '{{.State.Health.Status}}' "$relay_id")" == healthy ]] || { echo 'Relay unhealthy' >&2; false; }
[[ "$("${COMPOSE[@]}" ps -q backend)" == "$backend_id" ]] || { echo 'Backend changed during relay deployment' >&2; false; }
trap - ERR INT TERM
echo 'Relay started; inbound WhatsApp remains disabled until a coordinated activation.'
