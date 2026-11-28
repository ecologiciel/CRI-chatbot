#!/usr/bin/env bash
# Coordinated, additive WhatsApp/agent schema release; all new paths remain off.
set -Eeuo pipefail
umask 077
DEPLOY_DIR=${DEPLOY_DIR:-/opt/chatbot-demo}
BACKUP_DIR=${BACKUP_DIR:-/root/chatbot-backups}
PROJECT=${COMPOSE_PROJECT_NAME:-chatbot-demo}
: "${EXPECTED_HEAD:?Expected source commit required}"
: "${CANDIDATE_BACKEND:?Tested backend image required}"
: "${CANDIDATE_ADMIN:?Tested admin image required}"
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
running=$("${compose[@]}" --profile whatsapp-durable --profile agent-replies --profile dossier-import --profile dossier-outbox ps --status running --services)
if grep -Eq '^(whatsapp-inbox-worker|agent-reply-worker|dossier-import-worker|dossier-outbox-worker)$' <<< "$running"; then
  echo 'Durable worker is active; coordinated cutover required' >&2; exit 1
fi
for service in backend frontend-admin ingestion-worker learning-worker purge-worker postgres; do
  grep -Fxq "$service" <<< "$running" || { echo "Unavailable: $service" >&2; exit 1; }
done
mapfile -t tags < <("${compose[@]}" config --no-interpolate --format json | python3 -c '
import json,re,sys
s=json.load(sys.stdin)["services"]
b,a=s["backend"]["image"],s["frontend-admin"]["image"]
if any(not re.fullmatch(r"[a-z0-9][a-z0-9._/:\-]*",v) for v in (b,a)): raise SystemExit("Invalid image tag")
allowed={"backend","extractor","ingestion-worker","learning-worker","purge-worker","whatsapp-inbox-worker","agent-reply-worker","demo-bootstrap"}
if b==a or any(v.get("image") in (b,a) for k,v in s.items() if k not in allowed|{"frontend-admin"}): raise SystemExit("Image tag collision")
if any(s[k]["image"]!=b for k in ("ingestion-worker","learning-worker","purge-worker")): raise SystemExit("Application tags differ")
print(b);print(a)')
[[ ${#tags[@]} -eq 2 ]] || { echo 'Unable to validate tags' >&2; exit 1; }
backend_tag=${tags[0]}; admin_tag=${tags[1]}
"${compose[@]}" config --format json | python3 -c '
import json,sys
v=json.load(sys.stdin)["services"]["backend"]["environment"]
for name in ("WHATSAPP_DURABLE_INBOX_ENABLED","WHATSAPP_TENANT_WEBHOOK_ENABLED","AGENT_REPLY_OUTBOX_ENABLED"):
 if str(v.get(name,"false")).lower() not in ("false","0","no","off"): raise SystemExit("New intake or outbox is enabled")
if str(v.get("WHATSAPP_CONFIG_REQUIRE_ENCRYPTION", "false")).lower() not in ("true","1","yes","on"): raise SystemExit("Strict channel encryption is disabled")'
new_backend=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_BACKEND")
new_admin=$(docker image inspect -f '{{.Id}}' "$CANDIDATE_ADMIN")
[[ "$new_backend" =~ ^sha256:[a-f0-9]{64}$ && "$new_admin" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
bundle=$(mktemp -d "$BACKUP_DIR/agent-migration.XXXXXXXX")
override="$bundle/rollback.yml"
printf 'services:\n' > "$override"
for service in backend frontend-admin ingestion-worker learning-worker purge-worker; do
  id=$("${compose[@]}" ps -q "$service")
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || exit 1
  original=$(docker inspect -f '{{.Image}}' "$id")
  [[ "$original" =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
  tag="agent-migration-$(basename "$bundle" | tr '[:upper:]' '[:lower:]')-$service:before"
  docker tag "$original" "$tag"
  printf '  %s:\n    image: %s\n' "$service" "$tag" >> "$override"
done
old_backend=$(docker inspect -f '{{.Image}}' "$("${compose[@]}" ps -q backend)")
old_admin=$(docker inspect -f '{{.Image}}' "$("${compose[@]}" ps -q frontend-admin)")
[[ "$(docker image inspect -f '{{.Id}}' "$backend_tag")" == "$old_backend" && "$(docker image inspect -f '{{.Id}}' "$admin_tag")" == "$old_admin" ]] || { echo 'Application tags differ from running images' >&2; exit 1; }
restore_container="agent-restore-$(basename "$bundle" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')"
if docker inspect "$restore_container" >/dev/null 2>&1; then echo 'Restore fixture collision' >&2; exit 1; fi
printf '%s\n' prepared > "$bundle/state"
echo "Recovery bundle: $bundle"
stopped=0
cleanup_restore(){ docker rm -fv "$restore_container" >/dev/null 2>&1 || true; }
rollback(){
  local rc=$?; (( rc != 0 )) || rc=1
  trap - ERR INT TERM
  cleanup_restore
  if (( stopped )); then
    set +e
    docker tag "$old_backend" "$backend_tag" && docker tag "$old_admin" "$admin_tag" && \
      "${compose[@]}" -f "$override" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend frontend-admin ingestion-worker learning-worker purge-worker && \
      "${compose[@]}" exec -T backend python -m app.scripts.healthcheck
    if [[ $? == 0 ]]; then printf '%s\n' rolled_back_schema_may_be_upgraded > "$bundle/state"; echo "Previous images restored; database migration may remain applied: $bundle" >&2
    else printf '%s\n' manual_recovery_required > "$bundle/state"; echo "Rollback requires attention: $bundle" >&2; fi
  fi
  exit "$rc"
}
trap rollback ERR INT TERM
stopped=1
printf '%s\n' stopping_services > "$bundle/state"
"${compose[@]}" stop -t 780 ingestion-worker learning-worker purge-worker frontend-admin backend
state=$("${compose[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT (SELECT version_num FROM public.alembic_version) || '\''|'\'' || (SELECT count(*) FROM public.whatsapp_inbox_events) || '\''|'\'' || (SELECT count(*) FROM public.whatsapp_status_events) || '\''|'\'' || (SELECT count(*) FROM public.tenants WHERE COALESCE(jsonb_typeof(whatsapp_config::jsonb), '\''null'\'') <> '\''null'\'')"')
[[ "$state" == '0019a_phone|0|0|0' ]] || { echo 'Database state changed; migration refused' >&2; false; }
"${compose[@]}" exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl -Fc' > "$bundle/pre-migration.dump"
"${compose[@]}" exec -T postgres pg_restore --list < "$bundle/pre-migration.dump" > /dev/null
# Restore into a network-isolated disposable database; never expose a port.
docker run -d --name "$restore_container" --network none -e POSTGRES_USER=fixture -e POSTGRES_PASSWORD=fixture-pass -e POSTGRES_DB=ragtest_restore postgres:16-alpine >/dev/null
for i in $(seq 1 60); do docker exec "$restore_container" pg_isready -U fixture -d ragtest_restore >/dev/null 2>&1 && break; sleep 1; done
docker exec -i "$restore_container" pg_restore -U fixture -d ragtest_restore --no-owner --no-acl --exit-on-error < "$bundle/pre-migration.dump"
docker exec "$restore_container" psql -U fixture -d ragtest_restore -v ON_ERROR_STOP=1 -Atqc 'SELECT count(*) FROM public.tenants' >/dev/null
cleanup_restore
echo 'PostgreSQL backup restored in isolated fixture'
printf '%s\n' migrating > "$bundle/state"
docker tag "$new_backend" "$backend_tag"
docker tag "$new_admin" "$admin_tag"
"${compose[@]}" run --rm --no-deps --pull never backend alembic upgrade head
revision=$("${compose[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT version_num FROM public.alembic_version"')
[[ "$revision" == 0019d_reply ]] || { echo 'Unexpected migration revision' >&2; false; }
printf '%s\n' starting_candidate > "$bundle/state"
"${compose[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 backend frontend-admin ingestion-worker learning-worker purge-worker
"${compose[@]}" exec -T backend python -m app.scripts.healthcheck
"${compose[@]}" exec -T backend python -c 'from app.core.config import get_settings; s=get_settings(); assert s.whatsapp_config_require_encryption and not s.whatsapp_durable_inbox_enabled and not s.whatsapp_tenant_webhook_enabled and not s.agent_reply_outbox_enabled'
for service in backend frontend-admin ingestion-worker learning-worker purge-worker; do
  id=$("${compose[@]}" ps -q "$service")
  expected=$new_backend; [[ "$service" == frontend-admin ]] && expected=$new_admin
  [[ -n "$id" && "$(docker inspect -f '{{.State.Running}}' "$id")" == true && "$(docker inspect -f '{{.Image}}' "$id")" == "$expected" ]] || { echo "Unexpected service state: $service" >&2; false; }
done
printf '%s\n' completed > "$bundle/state"
trap - ERR INT TERM
echo "Agent schema release complete, all new paths remain disabled: $bundle"
