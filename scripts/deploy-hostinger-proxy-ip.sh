#!/usr/bin/env bash
# Change only the API image; leave all durable workers and their images intact.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_API:?Tested API image required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || exit 1
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || exit 1
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || exit 1
exec 8> .kms-rotation.lock; flock -x -n 8 || { echo 'KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"; flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?TRUSTED_PROXY_IP_SECRET[[:space:]]*=' .env.demo; then
  echo 'Proxy proof already configured; refusing replacement' >&2; exit 1
fi
c=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml --profile whatsapp-durable --profile agent-replies --profile local-wa-relay --profile dossier-import --profile dossier-outbox)
api_tag=$("${c[@]}" config --no-interpolate --format json | python3 -c '
import json,re,sys
s=json.load(sys.stdin)["services"]; tag=s["backend"]["image"]
if not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*",tag): raise SystemExit("Invalid API image tag")
if any(item.get("image")==tag for name,item in s.items() if name!="backend"): raise SystemExit("API tag is shared")
print(tag)')
api_id=$("${c[@]}" ps -q backend)
[[ -n "$api_id" && "$(docker inspect -f '{{.State.Health.Status}}' "$api_id")" == healthy ]] || { echo 'API unavailable' >&2; exit 1; }
old=$(docker inspect -f '{{.Image}}' "$api_id")
new=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_API")
[[ "$old" =~ ^sha256:[a-f0-9]{64}$ && "$new" =~ ^sha256:[a-f0-9]{64}$ && "$new" != "$old" ]] || exit 1
[[ "$(docker image inspect -f '{{.Id}}' "$api_tag")" == "$old" ]] || { echo 'API compatibility tag not prepared' >&2; exit 1; }
declare -A worker_ids
for service in agent-reply-worker whatsapp-inbox-worker ingestion-worker learning-worker purge-worker; do
  id=$("${c[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$old" ]] || { echo "Unexpected worker state: $service" >&2; exit 1; }
  worker_ids[$service]=$id
done
relay=$("${c[@]}" ps -q whatsapp-relay)
[[ -n "$relay" && "$(docker inspect -f '{{.State.Health.Status}}' "$relay")" == healthy ]] || { echo 'Relay unavailable' >&2; exit 1; }
"${c[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and s.agent_reply_outbox_enabled and s.whatsapp_durable_inbox_enabled and s.whatsapp_tenant_webhook_enabled'
bundle=$(mktemp -d "$BACKUP_DIR/proxy-ip-release.XXXXXXXX")
cp -p -- .env.demo "$bundle/env.before"; chmod 600 "$bundle/env.before"
rollback_tag="chatbot-demo-api:rollback-${bundle##*.}"
if docker image inspect "$rollback_tag" >/dev/null 2>&1; then echo 'Rollback image tag already exists' >&2; exit 1; fi
docker tag "$old" "$rollback_tag"
printf '%s\n' "$old" > "$bundle/api.image"
printf '%s\n' "$rollback_tag" > "$bundle/api.rollback-tag"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    cp -p -- "$bundle/env.before" .env.demo && docker tag "$old" "$api_tag" && \
      "${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend && \
      "${c[@]}" exec -T backend python -m app.scripts.healthcheck
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo "Previous API restored: $bundle" >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "API rollback needs attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
proof=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
[[ "$proof" =~ ^[a-f0-9]{64}$ ]] || exit 1
printf '\nTRUSTED_PROXY_IP_SECRET=%s\n' "$proof" >> .env.demo
unset proof
chmod 600 .env.demo
docker tag "$new" "$api_tag"
printf '%s\n' starting_candidate > "$bundle/state"
"${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend
"${c[@]}" exec -T backend python -m app.scripts.healthcheck
"${c[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert len(s.trusted_proxy_ip_secret)==64 and s.whatsapp_config_require_encryption and s.agent_reply_outbox_enabled and s.whatsapp_durable_inbox_enabled and s.whatsapp_tenant_webhook_enabled'
[[ "$(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q backend)")" == "$new" ]] || { echo 'Unexpected API image' >&2; false; }
for service in "${!worker_ids[@]}"; do
  [[ "$("${c[@]}" ps -q "$service")" == "${worker_ids[$service]}" && "$(docker inspect -f '{{.State.Running}}' "${worker_ids[$service]}")" == true ]] || { echo "Worker changed: $service" >&2; false; }
done
[[ "$("${c[@]}" ps -q whatsapp-relay)" == "$relay" && "$(docker inspect -f '{{.State.Health.Status}}' "$relay")" == healthy ]] || { echo 'Relay changed or unhealthy' >&2; false; }
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Proxy IP release installed; verify external attribution and forwarding boundary: $bundle"
