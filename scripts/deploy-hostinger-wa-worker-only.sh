#!/usr/bin/env bash
# Release a tested inbox worker image while preserving every other service.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_WORKER:?Tested worker image required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || exit 1
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || exit 1
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || exit 1
exec 8> .kms-rotation.lock; flock -x -n 8 || { echo 'KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"; flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
c=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml --profile whatsapp-durable --profile agent-replies --profile local-wa-relay --profile dossier-import --profile dossier-outbox)
tag=$("${c[@]}" config --no-interpolate --format json | python3 -c '
import json,re,sys
s=json.load(sys.stdin)["services"]; tag=s["whatsapp-inbox-worker"]["image"]
if not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*",tag): raise SystemExit("Invalid worker tag")
if any(item.get("image")==tag for name,item in s.items() if name!="whatsapp-inbox-worker"): raise SystemExit("Worker tag is shared")
print(tag)')
mapfile -t worker_ids < <("${c[@]}" ps -q whatsapp-inbox-worker)
[[ ${#worker_ids[@]} == 1 && "$(docker inspect -f '{{.State.Running}}' "${worker_ids[0]}")" == true ]] || { echo 'Expected exactly one running inbox worker' >&2; exit 1; }
old=$(docker inspect -f '{{.Image}}' "${worker_ids[0]}")
candidate=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_WORKER")
[[ "$old" =~ ^sha256:[a-f0-9]{64}$ && "$candidate" =~ ^sha256:[a-f0-9]{64}$ && "$old" != "$candidate" ]] || exit 1
if docker image inspect "$tag" >/dev/null 2>&1; then
  [[ "$(docker image inspect -f '{{.Id}}' "$tag")" == "$old" ]] || { echo 'Worker tag points to a different image' >&2; exit 1; }
fi
declare -A preserved
for service in backend agent-reply-worker ingestion-worker learning-worker purge-worker whatsapp-relay; do
  id=$("${c[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || { echo "Unavailable: $service" >&2; exit 1; }
  preserved[$service]=$id
done
[[ "$(docker inspect -f '{{.State.Health.Status}}' "${preserved[backend]}")" == healthy ]] || exit 1
bundle=$(mktemp -d "$BACKUP_DIR/wa-worker-release.XXXXXXXX")
rollback_tag="chatbot-wa-inbox:rollback-${bundle##*.}"
if docker image inspect "$rollback_tag" >/dev/null 2>&1; then echo 'Rollback tag already exists' >&2; exit 1; fi
docker tag "$old" "$rollback_tag"
printf '%s\n' "$old" > "$bundle/worker.image"
printf '%s\n' "$rollback_tag" > "$bundle/worker.rollback-tag"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    docker tag "$old" "$tag" && "${c[@]}" up -d --no-deps --no-build --force-recreate whatsapp-inbox-worker
    id=$("${c[@]}" ps -q whatsapp-inbox-worker)
    if [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$old" ]]; then
      printf '%s\n' rolled_back > "$bundle/state"; echo "Previous inbox worker restored: $bundle" >&2
    else
      printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Inbox worker rollback needs attention: $bundle" >&2
    fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
docker tag "$candidate" "$tag"
printf '%s\n' starting_candidate > "$bundle/state"
"${c[@]}" up -d --no-deps --no-build --force-recreate whatsapp-inbox-worker
id=$("${c[@]}" ps -q whatsapp-inbox-worker)
[[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$candidate" ]] || { echo 'Unexpected inbox worker' >&2; false; }
"${c[@]}" exec -T whatsapp-inbox-worker python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_durable_inbox_enabled and s.whatsapp_tenant_webhook_enabled'
# Wait longer than the previous heartbeat's 45-second TTL. Presence after
# this point must come from a worker started after replacement.
sleep 46
ready=0
for attempt in $(seq 1 30); do
  [[ "$(docker inspect -f '{{.State.Running}}' "$id" 2>/dev/null)" == true ]] || break
  if "${c[@]}" exec -T backend python -c 'import asyncio; from app.core.redis import init_redis,close_redis,get_redis
async def check():
 await init_redis()
 try: return bool(await get_redis().exists("system:whatsapp_inbox:worker_heartbeat"))
 finally: await close_redis()
assert asyncio.run(check())' >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" == 1 ]] || { echo 'Inbox worker heartbeat unavailable' >&2; false; }
for service in "${!preserved[@]}"; do
  [[ "$("${c[@]}" ps -q "$service")" == "${preserved[$service]}" && "$(docker inspect -f '{{.State.Running}}' "${preserved[$service]}")" == true ]] || { echo "Service changed: $service" >&2; false; }
done
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Inbox worker release complete: $bundle"
