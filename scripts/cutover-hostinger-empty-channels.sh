#!/usr/bin/env bash
# One-time strict channel encryption cutover, ONLY when no channels exist.
# No database migration is performed. A recovery bundle is retained on disk.
set -Eeuo pipefail
umask 077

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
PROJECT="${COMPOSE_PROJECT_NAME:-chatbot-demo}"
: "${CANDIDATE_BACKEND:?Specify the tested backend image ID or tag}"
: "${CANDIDATE_ADMIN:?Specify the tested admin image ID or tag}"
: "${EXPECTED_HEAD:?Specify the expected deployment Git commit}"
[[ "$PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo 'Invalid project' >&2; exit 1; }
cd "$DEPLOY_DIR"
[[ -f .env.demo && ! -L .env.demo && -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || { echo 'Unsafe deployment paths' >&2; exit 1; }
[[ ! -L .kms-rotation.lock && ! -L .kms-maintenance && ! -e .kms-maintenance/journal && ! -L .kms-maintenance/journal ]] || { echo 'Unsafe or unfinished KMS maintenance' >&2; exit 1; }
[[ ! -L "$BACKUP_DIR/.cold-backup.lock" && ! -e "$BACKUP_DIR/.cold-backup-services" && ! -L "$BACKUP_DIR/.cold-backup-services" ]] || { echo 'Unsafe or unfinished backup' >&2; exit 1; }
exec 8> .kms-rotation.lock
flock -x -n 8 || { echo 'Backup or KMS maintenance in progress' >&2; exit 1; }
exec 9> "$BACKUP_DIR/.cold-backup.lock"
flock -x -n 9 || { echo 'Backup in progress' >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" && -z "$(git status --porcelain --untracked-files=no)" ]] || { echo 'Unexpected or modified source tree' >&2; exit 1; }
BACKUP_DIR="$BACKUP_DIR" BACKUP_VERIFY_HASH=1 bash scripts/backup/check-hostinger-backup.sh
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?WHATSAPP_CONFIG_REQUIRE_ENCRYPTION[[:space:]]*=' .env.demo; then
  echo 'Existing strict-mode setting requires a separate procedure' >&2; exit 1
fi
COMPOSE=(docker compose --project-name "$PROJECT" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
image_tags=$("${COMPOSE[@]}" config --no-interpolate --format json | python3 -c '
import json, re, sys
s = json.load(sys.stdin)["services"]
backend, admin = s["backend"]["image"], s["frontend-admin"]["image"]
if any(not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*", v) for v in (backend, admin)):
    raise SystemExit("Invalid application image tag")
protected = {s[name]["image"] for name in ("postgres", "redis", "qdrant", "minio") if name in s}
if backend == admin or backend in protected or admin in protected:
    raise SystemExit("Application image tag conflicts with another service")
print(backend)
print(admin)
')
backend_tag=${image_tags%%$'\n'*}
admin_tag=${image_tags#*$'\n'}
services=(backend ingestion-worker learning-worker purge-worker frontend-admin)
running=$("${COMPOSE[@]}" --profile whatsapp-durable --profile dossier-import --profile dossier-outbox --profile agent-replies ps --status running --services)
if grep -Eq '^(whatsapp-inbox-worker|dossier-import-worker|dossier-outbox-worker|agent-reply-worker)$' <<< "$running"; then
  echo 'Durable worker is active; coordinated migration required' >&2; exit 1
fi
for service in "${services[@]}"; do
  grep -Fxq "$service" <<< "$running" || { echo "Required service unavailable: $service" >&2; exit 1; }
done
expected_backend=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_BACKEND")
expected_admin=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_ADMIN")
[[ "$expected_backend" =~ ^sha256:[a-f0-9]{64}$ && "$expected_admin" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid candidate image IDs' >&2; exit 1; }
bundle=$(mktemp -d "$BACKUP_DIR/channel-cutover.XXXXXXXX")
cp -p -- .env.demo "$bundle/env.before"
chmod 600 "$bundle/env.before"
override="$bundle/rollback.yml"
printf 'services:\n' > "$override"
for service in "${services[@]}"; do
  id=$("${COMPOSE[@]}" ps -q "$service")
  [[ -n "$id" ]] || { echo "Missing container: $service" >&2; exit 1; }
  image=$(docker inspect -f '{{.Image}}' "$id")
  [[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid original image ID' >&2; exit 1; }
  tag="channel-cutover-$(basename "$bundle" | tr '[:upper:]' '[:lower:]')-$service:before"
  docker tag "$image" "$tag"
  printf '  %s:\n    image: %s\n' "$service" "$tag" >> "$override"
done
chmod 600 "$override"
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
channel_count() {
  "${COMPOSE[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT count(*) FROM public.tenants WHERE COALESCE(jsonb_typeof(whatsapp_config::jsonb), '\''null'\'') <> '\''null'\''"'
}
stopped=0
candidate_started=0
rollback() {
  local rc=$?
  (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  if (( stopped )); then
    set +e
    if ! "${COMPOSE[@]}" stop -t 780 "${services[@]}" >/dev/null 2>&1; then
      printf '%s\n' manual_recovery_required > "$bundle/state"
      echo "Cannot stop services for rollback. Recovery bundle: $bundle" >&2
      exit "$rc"
    fi
    count=0
    if (( candidate_started )); then count=$(channel_count 2>/dev/null); fi
    if [[ "$count" != 0 ]]; then
      printf '%s\n' manual_recovery_required > "$bundle/state"
      echo "Rollback refused: channel state is not confirmed empty. Recovery bundle: $bundle" >&2
      exit "$rc"
    fi
    if ! cp -p -- "$bundle/env.before" .env.demo; then
      printf '%s\n' manual_recovery_required > "$bundle/state"
      echo "Cannot restore configuration. Recovery bundle: $bundle" >&2
      exit "$rc"
    fi
    # Restore common tags as well as each service's exact previously running image.
    old_backend=$(awk '$1 == "backend:" {getline; print $2}' "$override")
    old_admin=$(awk '$1 == "frontend-admin:" {getline; print $2}' "$override")
    docker tag "$old_backend" "$backend_tag" && docker tag "$old_admin" "$admin_tag" && \
      "${COMPOSE[@]}" -f "$override" up -d --no-deps --no-build --force-recreate "${services[@]}"
    if [[ $? == 0 ]]; then
      printf '%s\n' rolled_back > "$bundle/state"
      echo "Previous images restored; verify service health. Recovery bundle: $bundle" >&2
    else
      printf '%s\n' manual_recovery_required > "$bundle/state"
      echo "Automatic rollback failed. Recovery bundle: $bundle" >&2
    fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
stopped=1
printf '%s\n' stopping_services > "$bundle/state"
"${COMPOSE[@]}" stop -t 780 "${services[@]}"
[[ "$(channel_count)" == 0 ]] || { echo 'Existing channel requires the migration procedure' >&2; false; }
printf '\nWHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true\n' >> .env.demo
docker tag "$expected_backend" "$backend_tag"
docker tag "$expected_admin" "$admin_tag"
printf '%s\n' starting_candidate > "$bundle/state"
candidate_started=1
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend frontend-admin
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate ingestion-worker learning-worker purge-worker
"${COMPOSE[@]}" exec -T backend python -m app.scripts.healthcheck
"${COMPOSE[@]}" exec -T backend python -c 'from app.core.config import get_settings; assert get_settings().whatsapp_config_require_encryption is True'
for service in "${services[@]}"; do
  id=$("${COMPOSE[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || { echo "Service unavailable: $service" >&2; false; }
  expected=$expected_backend
  [[ "$service" == frontend-admin ]] && expected=$expected_admin
  [[ "$(docker inspect -f '{{.Image}}' "$id")" == "$expected" ]] || { echo "Unexpected image: $service" >&2; false; }
done
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Strict channel encryption cutover complete. Recovery bundle: $bundle"
