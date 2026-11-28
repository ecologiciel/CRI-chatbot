#!/usr/bin/env bash
# Destructive operations here target only generated fixture projects.
set -Eeuo pipefail
: "${TEST_OLD_BACKEND:?}" "${TEST_NEW_BACKEND:?}" "${TEST_OLD_ADMIN:?}" "${TEST_SCHEMA_SOURCE:?}" "${TEST_RELAY:?}"
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d /tmp/codex-wa-worker-mode.XXXXXXXX)
suffix=$(basename "$fixture" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
project="modetest${suffix}"
old="agenttest-${suffix}-old:test"
old_admin="agenttest-${suffix}-admin:test"
api="proxytest-${suffix}-api:test"
worker="workeronly-${suffix}:test"
bad="proxytest-${suffix}-bad:test"
other="proxytest-${suffix}-other:test"
cleanup(){
  rc=$?
  if (( rc != 0 )); then
    cat "$fixture/success.log" "$fixture/failure.log" "$fixture/race.log" 2>/dev/null || true
    docker logs --tail 30 "${project}-whatsapp-inbox-worker-1" 2>&1 || true
  fi
  if [[ "$project" =~ ^modetestcodexwaworkermode[a-z0-9]+$ && -f "$fixture/deploy/docker-compose.hostinger.yml" ]]; then
    docker compose -p "$project" --env-file "$fixture/deploy/.env.demo" -f "$fixture/deploy/docker-compose.hostinger.yml" --profile agent-replies --profile whatsapp-durable --profile local-wa-relay down -v --remove-orphans >/dev/null 2>&1 || true
    for file in "$fixture"/backups/wa-worker-release.*/worker.rollback-tag; do
      if [[ -f "$file" ]]; then
        read -r rollback_tag < "$file"
        [[ "$rollback_tag" =~ ^chatbot-wa-inbox:rollback-[a-zA-Z0-9]{8}$ ]] || { rc=1; continue; }
        docker image rm "$rollback_tag" >/dev/null 2>&1 || true
      fi
    done
  fi
  docker image rm "$old" "$old_admin" "$api" "$worker" "$bad" "$other" >/dev/null 2>&1 || true
  case "$fixture" in /tmp/codex-wa-worker-mode.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac
}
trap cleanup EXIT
mkdir -p "$fixture/deploy/scripts/backup" "$fixture/backups" "$fixture/wrapper"
docker tag "$TEST_OLD_BACKEND" "$old"
docker tag "$TEST_OLD_ADMIN" "$old_admin"
docker tag "$TEST_OLD_BACKEND" "$api"
docker tag "$TEST_OLD_BACKEND" "$worker"
printf "ARG BASE\nFROM \$BASE\nUSER root\nRUN rm /app/app/workers/whatsapp_inbox.py\nUSER cri\n" > "$fixture/Dockerfile"
docker build -q --build-arg BASE="$TEST_NEW_BACKEND" -t "$bad" "$fixture" >/dev/null
printf "ARG BASE\nFROM \$BASE\nLABEL fixture-version=older-worker\n" > "$fixture/Dockerfile"
docker build -q --build-arg BASE="$TEST_OLD_BACKEND" -t "$other" "$fixture" >/dev/null
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
  WHATSAPP_DURABLE_INBOX_ENABLED: 'true'
  WHATSAPP_TENANT_WEBHOOK_ENABLED: 'true'
  TRUSTED_PROXY_IP_SECRET: '\${TRUSTED_PROXY_IP_SECRET:-}'
  AGENT_REPLY_OUTBOX_ENABLED: 'true'
  WEBHOOK_PROXY_SHARED_SECRET: 'fixture-relay-secret'
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
    image: $api
    environment: *env
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    healthcheck: { test: ["CMD", "python3.12", "-m", "app.scripts.healthcheck"], interval: 2s, timeout: 3s, retries: 30 }
  frontend-admin:
    image: $old_admin
    environment: { HOSTNAME: 0.0.0.0 }
  ingestion-worker: { image: $other, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
  learning-worker: { image: $other, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
  purge-worker: { image: $other, environment: *env, entrypoint: ["python3.12", "-c", "import signal,sys; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()"], healthcheck: {disable: true} }
  agent-reply-worker:
    image: $old
    profiles: ["agent-replies"]
    environment: *env
    entrypoint: ["/bin/sh", "-c"]
    command: ['exec arq app.workers.agent_reply_outbox.WorkerSettings']
    healthcheck: { disable: true }
  whatsapp-inbox-worker:
    image: $worker
    profiles: ["whatsapp-durable"]
    environment: *env
    entrypoint: ["/bin/sh", "-c"]
    command: ['exec arq app.workers.whatsapp_inbox.WorkerSettings']
    healthcheck: { disable: true }
  whatsapp-relay:
    image: $TEST_RELAY
    profiles: ["local-wa-relay"]
    environment: { WEBHOOK_PROXY_SHARED_SECRET: fixture-relay-secret }
    healthcheck: { test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2)"], interval: 2s, timeout: 3s, retries: 30 }
EOF
printf 'services: {}\n' > "$fixture/deploy/docker-compose.hostinger.local.yml"
printf 'REHEARSAL_FAIL=0\nTRUSTED_PROXY_IP_SECRET=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' > "$fixture/deploy/.env.demo"
printf '#!/bin/sh\nexit 0\n' > "$fixture/deploy/scripts/backup/check-hostinger-backup.sh"
cd "$fixture/deploy"
git init -q
git config user.email fixture@example.invalid
git config user.name Fixture
git add docker-compose.hostinger.yml docker-compose.hostinger.local.yml scripts/backup/check-hostinger-backup.sh
git commit -qm fixture
export DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project"
export EXPECTED_HEAD="$(git rev-parse HEAD)"
c=(docker compose -p "$project" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml --profile agent-replies --profile whatsapp-durable --profile local-wa-relay)
initialise(){
  "${c[@]}" up -d postgres redis qdrant minio >/dev/null
  ready=0
  for i in $(seq 1 60); do
    if "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -Atqc 'SELECT 1' >/dev/null 2>&1; then
      sleep 2
      if "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -Atqc 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
    fi
    sleep 1
  done
  [[ "$ready" == 1 ]] || { echo 'Fixture PostgreSQL did not become ready' >&2; return 1; }
  docker exec "$TEST_SCHEMA_SOURCE" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-acl' | "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -v ON_ERROR_STOP=1 -q >/dev/null
  "${c[@]}" exec -T postgres psql -U fixture -d ragtest_release -v ON_ERROR_STOP=1 -q -c "INSERT INTO public.alembic_version VALUES ('0019d_reply')"
  "${c[@]}" up -d --wait --wait-timeout 120 backend frontend-admin ingestion-worker learning-worker purge-worker agent-reply-worker whatsapp-inbox-worker whatsapp-relay >/dev/null
}
initialise
for service in backend agent-reply-worker ingestion-worker learning-worker purge-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$fixture/before"
env_hash=$(sha256sum .env.demo)
CANDIDATE_WORKER="$TEST_NEW_BACKEND" bash "$root/deploy-hostinger-wa-worker-only.sh" > "$fixture/success.log" 2>&1
[[ "$(sha256sum .env.demo)" == "$env_hash" ]]
[[ "$(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q whatsapp-inbox-worker)")" == "$(docker image inspect -f '{{.Id}}' "$TEST_NEW_BACKEND")" ]]
for service in backend agent-reply-worker ingestion-worker learning-worker purge-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$fixture/after"
cmp "$fixture/before" "$fixture/after"
echo WA_WORKER_ONLY_SUCCESS_OK
"${c[@]}" down -v --remove-orphans >/dev/null
docker tag "$TEST_OLD_BACKEND" "$worker"
initialise
for service in backend agent-reply-worker ingestion-worker learning-worker purge-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$fixture/before"
if CANDIDATE_WORKER="$bad" bash "$root/deploy-hostinger-wa-worker-only.sh" > "$fixture/failure.log" 2>&1; then echo 'Expected candidate failure' >&2; exit 1; fi
grep -q 'Previous inbox worker restored' "$fixture/failure.log"
[[ "$(sha256sum .env.demo)" == "$env_hash" ]]
[[ "$(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q whatsapp-inbox-worker)")" == "$(docker image inspect -f '{{.Id}}' "$TEST_OLD_BACKEND")" ]]
for service in backend agent-reply-worker ingestion-worker learning-worker purge-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$fixture/after"
cmp "$fixture/before" "$fixture/after"
echo WA_WORKER_ONLY_ROLLBACK_OK
