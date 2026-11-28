#!/usr/bin/env bash
# Enable only the agent reply outbox on an empty, migrated installation.
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
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?AGENT_REPLY_OUTBOX_ENABLED[[:space:]]*=' .env.demo; then
  echo 'Existing outbox setting requires separate handling' >&2; exit 1
fi
compose=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
running=$("${compose[@]}" --profile agent-replies ps --status running --services)
grep -Fxq backend <<< "$running" || { echo 'API unavailable' >&2; exit 1; }
if grep -Fxq agent-reply-worker <<< "$running"; then echo 'Agent worker is already running' >&2; exit 1; fi
"${compose[@]}" config --format json | python3 -c '
import json,sys
v=json.load(sys.stdin)["services"]["backend"]["environment"]
for name in ("AGENT_REPLY_OUTBOX_ENABLED","WHATSAPP_DURABLE_INBOX_ENABLED","WHATSAPP_TENANT_WEBHOOK_ENABLED"):
 if str(v.get(name,"false")).lower() not in ("false","0","no","off"): raise SystemExit("Unexpected enabled mode")
if str(v.get("WHATSAPP_CONFIG_REQUIRE_ENCRYPTION","false")).lower() not in ("true","1","yes","on"): raise SystemExit("Strict channel encryption required")'
backend_id=$("${compose[@]}" ps -q backend)
backend_image=$(docker inspect -f '{{.Image}}' "$backend_id")
[[ "$backend_image" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
backend_tag=$("${compose[@]}" config --no-interpolate --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["backend"]["image"])')
[[ "$(docker image inspect -f '{{.Id}}' "$backend_tag")" == "$backend_image" ]] || { echo 'Backend tag differs from running image' >&2; exit 1; }
"${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and not s.agent_reply_outbox_enabled and not s.whatsapp_durable_inbox_enabled and not s.whatsapp_tenant_webhook_enabled'
state(){ "${compose[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT (SELECT version_num FROM public.alembic_version) || '\''|'\'' || (SELECT count(*) FROM public.agent_reply_outbox_events) || '\''|'\'' || (SELECT count(*) FROM public.tenants WHERE COALESCE(jsonb_typeof(whatsapp_config::jsonb), '\''null'\'') <> '\''null'\'')"'; }
[[ "$(state)" == '0019d_reply|0|0' ]] || { echo 'Schema, channel or outbox state changed' >&2; exit 1; }
bundle=$(mktemp -d "$BACKUP_DIR/agent-mode.XXXXXXXX")
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
      current=$(state 2>/dev/null)
      if [[ "$current" != '0019d_reply|0|0' ]]; then
        # Keep durable mode and try to preserve availability; never switch to
        # the legacy sender when an event or channel may have appeared.
        "${compose[@]}" up -d --no-deps --no-build --wait --wait-timeout 120 backend >/dev/null 2>&1 || true
        "${compose[@]}" --profile agent-replies up -d --no-deps --no-build agent-reply-worker >/dev/null 2>&1 || true
        printf '%s\n' manual_recovery_required > "$bundle/state"
        echo "Rollback refused because channel or outbox state changed: $bundle" >&2; exit "$rc"
      fi
      "${compose[@]}" --profile agent-replies stop -t 180 agent-reply-worker >/dev/null 2>&1 || true
    fi
    cp -p -- "$bundle/env.before" .env.demo && \
      "${compose[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend && \
      "${compose[@]}" exec -T backend python -m app.scripts.healthcheck && \
      "${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert not get_settings().agent_reply_outbox_enabled'
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo "Previous agent mode restored: $bundle" >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Rollback requires attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
printf '%s\n' stopping_api > "$bundle/state"
"${compose[@]}" stop -t 120 backend
[[ "$(state)" == '0019d_reply|0|0' ]] || { echo 'State changed before activation' >&2; false; }
flag_written=1
printf '\nAGENT_REPLY_OUTBOX_ENABLED=true\n' >> .env.demo
chmod 600 .env.demo
printf '%s\n' starting_candidate > "$bundle/state"
"${compose[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend
"${compose[@]}" --profile agent-replies up -d --no-deps --no-build --force-recreate agent-reply-worker
worker_id=$("${compose[@]}" --profile agent-replies ps -q agent-reply-worker)
[[ -n "$worker_id" && "$(docker inspect -f '{{.State.Running}}' "$worker_id")" == true && "$(docker inspect -f '{{.Image}}' "$worker_id")" == "$backend_image" ]] || { echo 'Unexpected worker state' >&2; false; }
"${compose[@]}" exec -T backend python -m app.scripts.healthcheck
"${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and s.agent_reply_outbox_enabled and not s.whatsapp_durable_inbox_enabled and not s.whatsapp_tenant_webhook_enabled'
"${compose[@]}" --profile agent-replies exec -T agent-reply-worker python -c 'from app.core.config import get_settings; assert get_settings().agent_reply_outbox_enabled'
# A stale heartbeat from a stopped worker can live for 45 seconds.
sleep 46
ready=0
for attempt in $(seq 1 30); do
  if "${compose[@]}" exec -T backend python -c 'import asyncio; from app.core.redis import init_redis,close_redis,get_redis; from app.services.escalation.reply_presence import HEARTBEAT_KEY
async def check():
 await init_redis()
 try: return bool(await get_redis().exists(HEARTBEAT_KEY))
 finally: await close_redis()
assert asyncio.run(check())' >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 && "$(docker inspect -f '{{.State.Running}}' "$worker_id")" == true ]] || { echo 'Agent worker heartbeat unavailable' >&2; false; }
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Agent reply outbox enabled; heartbeat seen, not proof of provider delivery: $bundle"
