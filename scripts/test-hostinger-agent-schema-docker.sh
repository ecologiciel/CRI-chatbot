#!/usr/bin/env bash
# Destructive operations here target only generated fixture projects.
set -Eeuo pipefail
: "${TEST_OLD_BACKEND:?}" "${TEST_NEW_BACKEND:?}" "${TEST_OLD_ADMIN:?}" "${TEST_NEW_ADMIN:?}" "${TEST_SCHEMA_SOURCE:?}"
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d /tmp/codex-agent-schema.XXXXXXXX)
suffix=$(basename "$fixture" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
project="agenttest${suffix}"
old="agenttest-${suffix}-old:test"
old_admin="agenttest-${suffix}-admin:test"
new="agenttest-${suffix}-new:test"
fail="agenttest-${suffix}-failure:test"
cleanup(){
  rc=$?
  if (( rc != 0 )); then cat "$fixture/success.log" "$fixture/failure.log" 2>/dev/null || true; fi
  if [[ "$project" =~ ^agenttestcodexagentschema[a-z0-9]+$ && -f "$fixture/deploy/docker-compose.hostinger.yml" ]]; then
    docker compose -p "$project" --env-file "$fixture/deploy/.env.demo" -f "$fixture/deploy/docker-compose.hostinger.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  docker image rm "$old" "$old_admin" "$new" "$fail" >/dev/null 2>&1 || true
  case "$fixture" in /tmp/codex-agent-schema.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac
}
trap cleanup EXIT
mkdir -p "$fixture/deploy/scripts/backup" "$fixture/backups" "$fixture/wrapper"
docker tag "$TEST_OLD_BACKEND" "$old"
docker tag "$TEST_OLD_ADMIN" "$old_admin"
docker tag "$TEST_NEW_BACKEND" "$new"
cat > "$fixture/wrapper/Dockerfile" <<EOF
FROM $new
USER root
COPY python-wrapper /usr/local/bin/python
RUN chmod 755 /usr/local/bin/python
USER cri
EOF
cat > "$fixture/wrapper/python-wrapper" <<'EOF'
#!/bin/sh
if [ "${REHEARSAL_FAIL:-0}" = 1 ] && [ "${1:-}" = -m ] && [ "${2:-}" = app.scripts.healthcheck ]; then exit 42; fi
exec /usr/local/bin/python3.12 "$@"
EOF
docker build -q -t "$fail" "$fixture/wrapper" >/dev/null
cat > "$fixture/deploy/docker-compose.hostinger.yml" <<EOF
x-backend: &env
  ENVIRONMENT: development
  POSTGRES_HOST: postgres
  POSTGRES_DB: ragtest_release
  POSTGRES_USER: fixture
  POSTGRES_PASSWORD: fixture-pass
  REDIS_HOST: redis
  REDIS_PASSWORD: fixture-pass
  QDRANT_HOST: qdrant
  MINIO_ENDPOINT: minio:9000
  MINIO_ROOT_USER: fixtureuser
  MINIO_ROOT_PASSWORD: fixture-pass
  KMS_MASTER_KEY: '0707070707070707070707070707070707070707070707070707070707070707'
  WHATSAPP_CONFIG_REQUIRE_ENCRYPTION: 'true'
  WHATSAPP_DURABLE_INBOX_ENABLED: 'false'
  WHATSAPP_TENANT_WEBHOOK_ENABLED: 'false'
  AGENT_REPLY_OUTBOX_ENABLED: 'false'
  REHEARSAL_FAIL: '\${REHEARSAL_FAIL:-0}'
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: fixture, POSTGRES_PASSWORD: fixture-pass, POSTGRES_DB: ragtest_release }
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass fixture-pass
  qdrant: { image: qdrant/qdrant:v1.12.1 }
  minio:
    image: dappros/minio:RELEASE.2025-09-07T16-13-09Z
    command: server /data
    environment: { MINIO_ROOT_USER: fixtureuser, MINIO_ROOT_PASSWORD: fixture-pass }
  backend:
    image: $old
    environment: *env
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    healthcheck: { test: ["CMD", "python3.12", "-m", "app.scripts.healthcheck"], interval: 2s, timeout: 3s, retries: 30 }
  frontend-admin:
    image: $old_admin
    environment: { HOSTNAME: 0.0.0.0 }
  ingestion-worker: { image: $old, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
  learning-worker: { image: $old, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
  purge-worker: { image: $old, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
EOF
printf 'services: {}\n' > "$fixture/deploy/docker-compose.hostinger.local.yml"
printf 'REHEARSAL_FAIL=0\n' > "$fixture/deploy/.env.demo"
printf '#!/bin/sh\nexit 0\n' > "$fixture/deploy/scripts/backup/check-hostinger-backup.sh"
cd "$fixture/deploy"
git init -q
git config user.email fixture@example.invalid
git config user.name Fixture
git add docker-compose.hostinger.yml docker-compose.hostinger.local.yml scripts/backup/check-hostinger-backup.sh
git commit -qm fixture
export DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project"
export EXPECTED_HEAD="$(git rev-parse HEAD)" CANDIDATE_ADMIN="$TEST_NEW_ADMIN"
c=(docker compose -p "$project" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
initialise(){
  "${c[@]}" up -d postgres redis qdrant minio >/dev/null
  for i in $(seq 1 60); do "${c[@]}" exec -T postgres pg_isready -U fixture -d ragtest_release >/dev/null 2>&1 && break; sleep 1; done
  docker exec "$TEST_SCHEMA_SOURCE" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-acl' | "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -v ON_ERROR_STOP=1 -q >/dev/null
  "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -v ON_ERROR_STOP=1 -q -c "INSERT INTO public.alembic_version VALUES ('0019a_phone')"
  "${c[@]}" up -d --wait --wait-timeout 120 backend frontend-admin ingestion-worker learning-worker purge-worker >/dev/null
}
initialise
export CANDIDATE_BACKEND="$new"
bash "$root/deploy-hostinger-agent-schema.sh" > "$fixture/success.log" 2>&1
[[ "$("${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -Atqc 'SELECT version_num FROM public.alembic_version')" == 0019d_reply ]]
grep -q 'PostgreSQL backup restored in isolated fixture' "$fixture/success.log"
echo AGENT_SCHEMA_RELEASE_SUCCESS_OK
"${c[@]}" down -v --remove-orphans >/dev/null
docker tag "$TEST_OLD_BACKEND" "$old"
docker tag "$TEST_OLD_ADMIN" "$old_admin"
printf 'REHEARSAL_FAIL=1\n' > .env.demo
initialise
export CANDIDATE_BACKEND="$fail"
if bash "$root/deploy-hostinger-agent-schema.sh" > "$fixture/failure.log" 2>&1; then echo 'Expected candidate health failure' >&2; exit 1; fi
grep -q 'Previous images restored; database migration may remain applied' "$fixture/failure.log"
[[ "$("${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -Atqc 'SELECT version_num FROM public.alembic_version')" == 0019d_reply ]]
[[ "$(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q backend)")" == "$(docker image inspect -f '{{.Id}}' "$TEST_OLD_BACKEND")" ]]
echo AGENT_SCHEMA_ROLLBACK_AFTER_MIGRATION_OK
