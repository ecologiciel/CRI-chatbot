#!/usr/bin/env bash
# Release only the administration UI while durable message workers remain up.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_ADMIN:?Tested administration image required}"
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
admin_tag=$("${c[@]}" config --no-interpolate --format json | python3 -c '
import json, re, sys
services = json.load(sys.stdin)["services"]
tag = services["frontend-admin"]["image"]
if not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*", tag): raise SystemExit("Invalid admin image tag")
if any(service.get("image") == tag for name, service in services.items() if name != "frontend-admin"):
    raise SystemExit("Admin image tag conflicts with another service")
print(tag)
')
admin_id=$("${c[@]}" ps -q frontend-admin)
[[ -n "$admin_id" && "$(docker inspect -f '{{.State.Health.Status}}' "$admin_id")" == healthy ]] || { echo 'Administration unavailable' >&2; exit 1; }
old=$(docker inspect -f '{{.Image}}' "$admin_id")
new=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_ADMIN")
[[ "$old" =~ ^sha256:[a-f0-9]{64}$ && "$new" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
[[ "$(docker image inspect -f '{{.Id}}' "$admin_tag")" == "$old" ]] || { echo 'Running admin image differs from tag' >&2; exit 1; }
for service in backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay; do
  id=$("${c[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || { echo "Required service unavailable: $service" >&2; exit 1; }
done
bundle=$(mktemp -d "$BACKUP_DIR/admin-release.XXXXXXXX")
printf '%s\n' "$old" > "$bundle/admin.image"
rollback_tag="chatbot-demo-admin:rollback-${bundle##*.}"
if docker image inspect "$rollback_tag" >/dev/null 2>&1; then echo 'Rollback image tag already exists' >&2; exit 1; fi
docker tag "$old" "$rollback_tag"
printf '%s\n' "$rollback_tag" > "$bundle/admin.rollback-tag"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    docker tag "$old" "$admin_tag" && "${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 frontend-admin
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo "Previous administration restored: $bundle" >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Administration rollback needs attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
printf '%s\n' starting_candidate > "$bundle/state"
docker tag "$new" "$admin_tag"
"${c[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 frontend-admin
new_id=$("${c[@]}" ps -q frontend-admin)
[[ -n "$new_id" && "$(docker inspect -f '{{.Image}}' "$new_id")" == "$new" && "$(docker inspect -f '{{.State.Health.Status}}' "$new_id")" == healthy ]] || { echo 'Unexpected administration state' >&2; false; }
for service in backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay; do
  id=$("${c[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || { echo "Service unavailable: $service" >&2; false; }
done
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Administration release complete: $bundle"
