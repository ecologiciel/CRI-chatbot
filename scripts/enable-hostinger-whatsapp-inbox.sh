#!/usr/bin/env bash
# Enable institution-specific durable intake on an empty installation.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || exit 1
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || exit 1
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || exit 1
exec 8> .kms-rotation.lock; flock -x -n 8 || { echo 'KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"; flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?(WHATSAPP_DURABLE_INBOX_ENABLED|WHATSAPP_TENANT_WEBHOOK_ENABLED)[[:space:]]*=' .env.demo; then
  echo 'Existing inbox settings require separate handling' >&2; exit 1
fi
c=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml --profile whatsapp-durable --profile agent-replies --profile local-wa-relay)
running=$("${c[@]}" ps --status running --services)
for name in backend agent-reply-worker whatsapp-relay; do grep -Fxq "$name" <<< "$running" || { echo "Missing service: $name" >&2; exit 1; }; done
if grep -Fxq whatsapp-inbox-worker <<< "$running"; then echo 'Inbox worker already running' >&2; exit 1; fi
backend_id=$("${c[@]}" ps -q backend)
agent_id=$("${c[@]}" ps -q agent-reply-worker)
relay_id=$("${c[@]}" ps -q whatsapp-relay)
backend_image=$(docker inspect -f '{{.Image}}' "$backend_id")
[[ "$backend_image" =~ ^sha256:[a-f0-9]{64}$ && "$(docker inspect -f '{{.State.Health.Status}}' "$backend_id")" == healthy && "$(docker inspect -f '{{.State.Health.Status}}' "$relay_id")" == healthy ]] || exit 1
backend_tag=$("${c[@]}" config --no-interpolate --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["backend"]["image"])')
[[ "$(docker image inspect -f '{{.Id}}' "$backend_tag")" == "$backend_image" ]] || { echo 'Backend tag differs from running image' >&2; exit 1; }
"${c[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and s.agent_reply_outbox_enabled and not s.whatsapp_durable_inbox_enabled and not s.whatsapp_tenant_webhook_enabled and s.webhook_proxy_shared_secret'
state(){ "${c[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT (SELECT version_num FROM public.alembic_version) || '\''|'\'' || (SELECT count(*) FROM public.whatsapp_inbox_events) || '\''|'\'' || (SELECT count(*) FROM public.whatsapp_status_events) || '\''|'\'' || (SELECT count(*) FROM public.tenants WHERE COALESCE(jsonb_typeof(whatsapp_config::jsonb), '\''null'\'') <> '\''null'\'')"'; }
[[ "$(state)" == '0019d_reply|0|0|0' ]] || { echo 'Schema, channels or inbox state changed' >&2; exit 1; }
bundle=$(mktemp -d "$BACKUP_DIR/whatsapp-inbox.XXXXXXXX")
cp -p -- .env.demo "$bundle/env.before"; chmod 600 "$bundle/env.before"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
flag_written=0
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    if (( flag_written )); then
      quiesced=1
      "${c[@]}" stop -t 120 backend >/dev/null 2>&1 || quiesced=0
      "${c[@]}" stop -t 180 whatsapp-inbox-worker >/dev/null 2>&1 || quiesced=0
      current=$(state 2>/dev/null)
      if [[ "$quiesced" != 1 || "$current" != '0019d_reply|0|0|0' ]]; then
        "${c[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 backend >/dev/null 2>&1 || true
        "${c[@]}" up -d --no-deps --no-build whatsapp-inbox-worker >/dev/null 2>&1 || true
        printf '%s\n' manual_recovery_required > "$bundle/state"
        echo "Rollback refused because inbox or channel state changed: $bundle" >&2; exit "$rc"
      fi
    fi
    cp -p -- "$bundle/env.before" .env.demo && \
      "${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend && \
      "${c[@]}" exec -T backend python -m app.scripts.healthcheck && \
      "${c[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.agent_reply_outbox_enabled and not s.whatsapp_durable_inbox_enabled and not s.whatsapp_tenant_webhook_enabled'
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo "Previous inbox mode restored: $bundle" >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Rollback requires attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
printf '%s\n' stopping_api > "$bundle/state"
"${c[@]}" stop -t 120 backend
[[ "$(state)" == '0019d_reply|0|0|0' ]] || { echo 'State changed before activation' >&2; false; }
flag_written=1
printf '\nWHATSAPP_DURABLE_INBOX_ENABLED=true\nWHATSAPP_TENANT_WEBHOOK_ENABLED=true\n' >> .env.demo
chmod 600 .env.demo
printf '%s\n' starting_candidate > "$bundle/state"
"${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend
"${c[@]}" up -d --no-deps --no-build --force-recreate whatsapp-inbox-worker
worker_id=$("${c[@]}" ps -q whatsapp-inbox-worker)
[[ -n "$worker_id" && "$(docker inspect -f '{{.State.Running}}' "$worker_id")" == true && "$(docker inspect -f '{{.Image}}' "$worker_id")" == "$backend_image" ]] || { echo 'Unexpected inbox worker state' >&2; false; }
"${c[@]}" exec -T backend python -m app.scripts.healthcheck
"${c[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and s.agent_reply_outbox_enabled and s.whatsapp_durable_inbox_enabled and s.whatsapp_tenant_webhook_enabled'
"${c[@]}" exec -T whatsapp-inbox-worker python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_durable_inbox_enabled and s.whatsapp_tenant_webhook_enabled'
sleep 46
ready=0
for attempt in $(seq 1 30); do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$worker_id" 2>/dev/null)" != true || "$(docker inspect -f '{{.State.Running}}' "$agent_id" 2>/dev/null)" != true ]]; then
    echo 'Worker stopped while waiting for heartbeat' >&2
    break
  fi
  if "${c[@]}" exec -T backend python -c 'import asyncio; from app.core.redis import init_redis,close_redis,get_redis
async def check():
 await init_redis()
 try: return bool(await get_redis().exists("system:whatsapp_inbox:worker_heartbeat")) and bool(await get_redis().exists("system:agent_reply_outbox:worker_heartbeat"))
 finally: await close_redis()
assert asyncio.run(check())' >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 && "$(docker inspect -f '{{.State.Running}}' "$worker_id")" == true && "$("${c[@]}" ps -q agent-reply-worker)" == "$agent_id" && "$(docker inspect -f '{{.State.Running}}' "$agent_id")" == true && "$(docker inspect -f '{{.State.Health.Status}}' "$relay_id")" == healthy ]] || { echo 'Worker heartbeat or service unavailable' >&2; false; }
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Durable WhatsApp intake enabled; provider integration requires separate testing: $bundle"
