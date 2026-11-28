#!/usr/bin/env bash
# Additive channel configuration release: no database or worker changes.
set -Eeuo pipefail
umask 077
DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
PROJECT="${COMPOSE_PROJECT_NAME:-chatbot-demo}"
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_BACKEND:?Tested backend image required}"
: "${CANDIDATE_ADMIN:?Tested admin image required}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo 'Invalid project' >&2; exit 1; }
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || { echo 'Unsafe deployment paths' >&2; exit 1; }
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || { echo 'Unsafe KMS state' >&2; exit 1; }
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || { echo 'Unsafe backup state' >&2; exit 1; }
exec 8> .kms-rotation.lock
flock -x -n 8 || { echo 'Backup or KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"
flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected or modified source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
COMPOSE=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
image_tags=$("${COMPOSE[@]}" config --no-interpolate --format json | python3 -c '
import json, re, sys
s = json.load(sys.stdin)["services"]
backend, admin = s["backend"]["image"], s["frontend-admin"]["image"]
if any(not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*", v) for v in (backend, admin)):
    raise SystemExit("Invalid application image tag")
shared = {"backend", "extractor", "ingestion-worker", "learning-worker", "purge-worker", "whatsapp-inbox-worker", "demo-bootstrap", "frontend-admin"}
protected = {entry["image"] for name, entry in s.items() if name not in shared and "image" in entry}
if backend == admin or backend in protected or admin in protected:
    raise SystemExit("Application image tag conflicts with another service")
print(backend); print(admin)
')
backend_tag=${image_tags%%$'\n'*}
admin_tag=${image_tags#*$'\n'}
backend_id=$("${COMPOSE[@]}" ps -q backend)
admin_id=$("${COMPOSE[@]}" ps -q frontend-admin)
[[ -n "$backend_id" && -n "$admin_id" ]] || { echo 'Required services unavailable' >&2; exit 1; }
old_backend=$(docker inspect -f '{{.Image}}' "$backend_id")
old_admin=$(docker inspect -f '{{.Image}}' "$admin_id")
new_backend=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_BACKEND")
new_admin=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_ADMIN")
for id in "$old_backend" "$old_admin" "$new_backend" "$new_admin"; do [[ "$id" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid image identity' >&2; exit 1; }; done
[[ "$(docker image inspect -f '{{.Id}}' "$backend_tag")" == "$old_backend" && "$(docker image inspect -f '{{.Id}}' "$admin_tag")" == "$old_admin" ]] || { echo 'Running images differ from deployment tags' >&2; exit 1; }
"${COMPOSE[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert get_settings().whatsapp_config_require_encryption is True'
for service in ingestion-worker learning-worker purge-worker; do
  id=$("${COMPOSE[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$old_backend" ]] || { echo "Unexpected worker state: $service" >&2; exit 1; }
done
bundle=$(mktemp -d "$BACKUP_DIR/channel-config-release.XXXXXXXX")
printf '%s\n' "$old_backend" > "$bundle/backend.image"
printf '%s\n' "$old_admin" > "$bundle/admin.image"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
changed=0
rollback() {
  local rc=$?
  (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( changed )); then
    set +e
    docker tag "$old_backend" "$backend_tag" && docker tag "$old_admin" "$admin_tag" && \
      "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend frontend-admin && \
      "${COMPOSE[@]}" exec -T backend python -m app.scripts.healthcheck
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back > "$bundle/state"; echo 'Previous API and administration restored' >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Rollback needs attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
changed=1
printf '%s\n' starting_candidate > "$bundle/state"
docker tag "$new_backend" "$backend_tag"
docker tag "$new_admin" "$admin_tag"
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend frontend-admin
"${COMPOSE[@]}" exec -T backend python -m app.scripts.healthcheck
"${COMPOSE[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert get_settings().whatsapp_config_require_encryption is True'
[[ "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q backend)")" == "$new_backend" && "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q frontend-admin)")" == "$new_admin" ]] || { echo 'Unexpected candidate image' >&2; false; }
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Channel configuration release complete. Recovery bundle: $bundle"
