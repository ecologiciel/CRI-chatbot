#!/usr/bin/env bash
# Release a tested backend to API and ingestion with exact-image rollback.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_BACKEND:?Tested image required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || exit 1
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || exit 1
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || exit 1
exec 8> .kms-rotation.lock
flock -x -n 8 || { echo 'KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"
flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
compose=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
backend_tag=$("${compose[@]}" config --no-interpolate --format json | python3 -c '
import json,re,sys
services=json.load(sys.stdin)["services"]
tag=services["backend"]["image"]
if not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*",tag): raise SystemExit("Invalid image tag")
if services["ingestion-worker"]["image"] != tag: raise SystemExit("Worker tag differs")
allowed={"backend","extractor","ingestion-worker","learning-worker","purge-worker","whatsapp-inbox-worker","agent-reply-worker","demo-bootstrap"}
if any(v.get("image")==tag for k,v in services.items() if k not in allowed): raise SystemExit("Image tag collision")
print(tag)')
candidate=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_BACKEND")
[[ "$candidate" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
bundle=$(mktemp -d "$BACKUP_DIR/embedding-release.XXXXXXXX")
override="$bundle/rollback.yml"
printf 'services:\n' > "$override"
for service in backend ingestion-worker; do
  id=$("${compose[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || { echo "Unavailable: $service" >&2; exit 1; }
  original=$(docker inspect -f '{{.Image}}' "$id")
  [[ "$original" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
  tag="embedding-$(basename "$bundle" | tr '[:upper:]' '[:lower:]')-$service:before"
  docker tag "$original" "$tag"
  printf '  %s:\n    image: %s\n' "$service" "$tag" >> "$override"
done
old_backend=$(docker inspect -f '{{.Image}}' "$("${compose[@]}" ps -q backend)")
[[ "$(docker image inspect -f '{{.Id}}' "$backend_tag")" == "$old_backend" ]] || { echo 'Backend tag does not match running image' >&2; exit 1; }
"${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert get_settings().whatsapp_config_require_encryption is True'
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    docker tag "$old_backend" "$backend_tag" && \
      "${compose[@]}" -f "$override" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend ingestion-worker && \
      "${compose[@]}" exec -T backend python -m app.scripts.healthcheck
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo 'Previous API and ingestion restored' >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Rollback needs attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
printf '%s\n' starting_candidate > "$bundle/state"
docker tag "$candidate" "$backend_tag"
"${compose[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend ingestion-worker
"${compose[@]}" exec -T backend python -m app.scripts.healthcheck
"${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert get_settings().whatsapp_config_require_encryption is True'
for service in backend ingestion-worker; do
  id=$("${compose[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$candidate" ]] || { echo "Unexpected service state: $service" >&2; false; }
done
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Embedding release complete: $bundle"
